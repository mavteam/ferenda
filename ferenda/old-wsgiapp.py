# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import *
from future import standard_library
standard_library.install_aliases()

from collections import defaultdict, OrderedDict, Counter, Iterable
from datetime import date, datetime
from io import BytesIO
from operator import itemgetter
from wsgiref.util import FileWrapper, request_uri
from urllib.parse import parse_qsl, urlencode
import inspect
import json
import logging
import mimetypes
import os
import pkg_resources
import re
import sys

from rdflib import URIRef, Namespace, Literal, Graph
from rdflib.namespace import DCTERMS
from lxml import etree
from layeredconfig import LayeredConfig, Defaults, INIFile

from ferenda import (DocumentRepository, FulltextIndex, Transformer,
                     Facet, ResourceLoader)
from ferenda import fulltextindex, util, elements
from ferenda.elements import html


class WSGIApp(object):

    """Implements a WSGI app.
    """

    def __init__(self, repos, inifile=None, **kwargs):
        self.repos = repos
        self.log = logging.getLogger("wsgi")

        # FIXME: Cut-n-paste of the method in Resources.__init__
        loadpaths = [ResourceLoader.make_loadpath(repo) for repo in repos]
        loadpath = ["."]  # cwd always has priority -- makes sense?
        for subpath in loadpaths:
            for p in subpath:
                if p not in loadpath:
                    loadpath.append(p)
        self.resourceloader = ResourceLoader(*loadpath)
        # FIXME: need to specify documentroot?
        defaults = DocumentRepository.get_default_options()
        if inifile:
            assert os.path.exists(
                inifile), "INI file %s doesn't exist (relative to %s)" % (inifile, os.getcwd())

        # NB: If both inifile and kwargs are specified, the latter
        # will take precedence. I think this is the expected
        # behaviour.
        self.config = LayeredConfig(Defaults(defaults),
                                    INIFile(inifile),
                                    Defaults(kwargs),
                                    cascade=True)

    ################################################################
    # Main entry point

    def __call__(self, environ, start_response):
        import logging
        profiling = 'profilepath' in self.config
        if profiling:
            import cProfile
            import pstats
            import codecs
            pr = cProfile.Profile()
            pr.enable()

        # FIXME: Under py2, values in environ are bytestrings, not
        # unicode strings, leading to random crashes throughout the
        # codebase when PATH_INFO or QUERY_STRING contains non-ascii
        # characters and being used with unicode strings (eg
        # "environ['PATH_INFO'].startswith(<unicodestring>)"). We
        # clean environ by decoding all bytestrings asap, ie
        # here. However, this causes request_uri (which expects
        # bytestrings in environ under py2) to fail...

        log = logging.getLogger("wsgiapp")
        path = environ['PATH_INFO']
        if not isinstance(path, str):
            path = path.decode("utf-8")

        # due to nginx config issues we might have to add a bogus
        # .diff suffix to our path. remove it as early as possible
        if path.endswith(".diff"):
            environ['PATH_INFO'] = environ['PATH_INFO'][:-5]
        url = request_uri(environ)
        qs = environ['QUERY_STRING']
        # self.log.info("Starting process for %s (path_info=%s, query_string=%s)" % (url, path, environ['QUERY_STRING']))
        # FIXME: routing infrastructure -- could be simplified?
        try:
            if path.startswith(self.config.searchendpoint):
                return self.search(environ, start_response)
            elif (path.startswith(self.config.apiendpoint) or
                  (self.config.legacyapi and path.startswith("/-/publ"))):
                return self.api(environ, start_response)
            elif ('stream' in qs):
                return self.stream(environ, start_response)
            else:
                return self.static(environ, start_response)
        except Exception:
            return self.exception(environ, start_response)
        finally:
            if profiling:
                pr.disable()
                sortby = 'cumulative'
                with codecs.open(self.config.profilepath, mode="a", encoding="utf-8") as fp:
                    fp.write("="*80 + "\n")
                    fp.write(url + "\n")
                    fp.write("Accept: %s\n\n" % environ.get("HTTP_ACCEPT"))
                    ps = pstats.Stats(pr, stream=fp).sort_stats(sortby)
                    ps.print_stats()

    ################################################################
    # WSGI methods

    def search(self, environ, start_response):
        """WSGI method, called by the wsgi app for requests that matches
           ``searchendpoint``."""
        queryparams = self._search_parse_query(environ['QUERY_STRING'])
        res, pager = self._search_run_query(queryparams)
        
        if pager['totalresults'] == 1:
            title = "1 match"
        else:
            title = "%s matches" % pager['totalresults']
        title += " for '%s'" % queryparams.get("q")
        body = html.Body()
        for r in res:
            if not 'dcterms_title' in r or r['dcterms_title'] is None:
                r['dcterms_title'] = r['uri']
            if r.get('dcterms_identifier', False):
                r['dcterms_title'] = r['dcterms_identifier'] + ": " + r['dcterms_title']
            body.append(html.Div(
                [html.H2([elements.Link(r['dcterms_title'], uri=r['uri'])]),
                 r.get('text', '')], **{'class': 'hit'}))
        pagerelem = self._search_render_pager(pager, queryparams,
                                              environ['PATH_INFO'])
        body.append(html.Div([
            html.P(["Results %(firstresult)s-%(lastresult)s "
                    "of %(totalresults)s" % pager]), pagerelem],
                                 **{'class':'pager'}))
        data = self._transform(title, body, environ, template="xsl/search.xsl")
        return self._return_response(data, start_response)

    def _return_response(self, data, start_response, status="200 OK",
                         contenttype="text/html; charset=utf-8", length=None):
        if length is None:
            length = len(data)
        if contenttype == "text/html":
            # add explicit charset if not provided by caller (it isn't by default)
            contenttype = "text/html; charset=utf-8"
        # logging.getLogger("wsgi").info("Calling start_response")
        start_response(self._str(status), [
            (self._str("X-WSGI-app"), self._str("ferenda")),
            (self._str("Content-Type"), self._str(contenttype)),
            (self._str("Content-Length"), self._str("%s" % length)),
        ])
        
        if isinstance(data, Iterable) and not isinstance(data, bytes):
            # logging.getLogger("wsgi").info("returning data as-is")
            return data
        else:
            # logging.getLogger("wsgi").info("returning data as-iterable")
            return iter([data])


    def api(self, environ, start_response):
        """WSGI method, called by the wsgi app for requests that matches
           ``apiendpoint``."""
        path = environ['PATH_INFO']
        if path.endswith(";stats"):
            d = self.stats()
        else:
            d = self.query(environ)
        data = json.dumps(d, indent=4, default=util.json_default_date,
                          sort_keys=True).encode('utf-8')
        return self._return_response(data, start_response,
                                     contenttype="application/json")

    def static(self, environ, start_response):
        """WSGI method, called by the wsgi app for all other requests not
        handled by :py:func:`~ferenda.Manager.search` or
        :py:func:`~ferenda.Manager.api`

        """
        path = environ['PATH_INFO']
        if not isinstance(path, str):
            path = path.decode("utf-8")
        fullpath = self.config.documentroot + path
        # we start by asking all repos "do you handle this path"?
        # default impl is to say yes if 1st seg == self.alias and the
        # rest can be treated as basefile yielding a existing
        # generated file.  a yes answer contains a FileWrapper around
        # the repo-selected file and optionally length (but not
        # status, always 200, or mimetype, always text/html). None
        # means no.
        fp = None
        reasons = OrderedDict()
        if not((path.startswith("/rsrc") or
                path == "/robots.txt")
               and os.path.exists(fullpath)):
            for repo in self.repos:
                supports = repo.requesthandler.supports(environ)
                if supports:
                    fp, length, status, mimetype = repo.requesthandler.handle(environ)
                elif hasattr(supports, 'reason'):
                    reasons[repo.alias] = supports.reason
                else:
                    reasons[repo.alias] = '(unknown reason)'
                if fp:
                    status = {200: "200 OK",
                              404: "404 Not found",
                              406: "406 Not Acceptable",
                              500: "500 Server error"}[status]
                    iterdata = FileWrapper(fp)
                    break
        # no repo handled the path
        if not fp:
            if self.config.legacyapi:  # rewrite the path to some resources. FIXME:
                          # shouldn't hardcode the "rsrc" path of the path
                if path == "/json-ld/context.json":
                    fullpath = self.config.documentroot + "/rsrc/api/context.json"
                elif path == "/var/terms":
                    fullpath = self.config.documentroot + "/rsrc/api/terms.json"
                elif path == "/var/common":
                    fullpath = self.config.documentroot + "/rsrc/api/common.json"
            if os.path.isdir(fullpath):
                fullpath = fullpath + "index.html"
            if os.path.exists(fullpath):
                ext = os.path.splitext(fullpath)[1]
                # if not mimetypes.inited:
                #     mimetypes.init()
                mimetype = mimetypes.types_map.get(ext, 'text/plain')
                status = "200 OK"
                length = os.path.getsize(fullpath)
                fp = open(fullpath, "rb")
                iterdata = FileWrapper(fp)
            else:
                mimetype = "text/html"
                reasonmsg = "\n".join(["%s: %s" % (k, reasons[k]) for k in reasons])
                msgbody = html.Body([html.H1("Document not found"),
                                     html.P(["The path %s was not found at %s" % (path, fullpath)]),
                                     html.P(["Examined %s repos" % (len(self.repos))]),
                                     html.Pre([reasonmsg])])
                iterdata = self._transform("404 Not found", msgbody, environ)
                status = "404 Not Found"
                length = None
        return self._return_response(iterdata, start_response, status, mimetype, length)

    def stream(self, environ, start_response):
        """WSGI method, called by the wsgi app for requests that indicate the
        need for a streaming response."""

        path = environ['PATH_INFO']
        if not isinstance(path, str):
            path = path.decode("utf-8")
        fullpath = self.config.documentroot + path
        # we start by asking all repos "do you handle this path"?
        # default impl is to say yes if 1st seg == self.alias and the
        # rest can be treated as basefile yielding a existing
        # generated file.  a yes answer contains a FileWrapper around
        # the repo-selected file and optionally length (but not
        # status, always 200, or mimetype, always text/html). None
        # means no.
        fp = None
        reasons = OrderedDict()
        if not((path.startswith("/rsrc") or
                path == "/robots.txt")
               and os.path.exists(fullpath)):
            for repo in self.repos:
                supports = repo.requesthandler.supports(environ)
                if supports:
                    return repo.requesthandler.stream(environ, start_response)
                elif hasattr(supports, 'reason'):
                    reasons[repo.alias] = supports.reason
                else:
                    reasons[repo.alias] = '(unknown reason)'
        # if we reach this, no repo handled the path
        mimetype = "text/html"
        reasonmsg = "\n".join(["%s: %s" % (k, reasons[k]) for k in reasons])
        msgbody = html.Body([html.H1("Document not found"),
                             html.P(["The path %s was not found at %s" % (path, fullpath)]),
                             html.P(["Examined %s repos" % (len(self.repos))]),
                             html.Pre([reasonmsg])])
        iterdata = self._transform("404 Not found", msgbody, environ)
        status = "404 Not Found"
        length = None
        return self._return_response(iterdata, start_response, status, mimetype, length)


    exception_heading = "Something is broken"
    exception_description = "Something went wrong when showing the page. Below is some troubleshooting information intended for the webmaster."
    def exception(self, environ, start_response):
        import traceback
        from pprint import pformat
        exc_type, exc_value, tb = sys.exc_info()
        tblines = traceback.format_exception(exc_type, exc_value, tb)
        tbstr = "\n".join(tblines)
        # render the error
        title = tblines[-1]
        body = html.Body([
            html.Div([html.H1(self.exception_heading),
                      html.P([self.exception_description]),
                      html.H2("Traceback"),
                      html.Pre([tbstr]),
                      html.H2("Variables"),
                      html.Pre(["request_uri: %s\nos.getcwd(): %s" % (request_uri(environ), os.getcwd())]),
                      html.H2("environ"),
                      html.Pre([pformat(environ)]),
                      html.H2("sys.path"),
                      html.Pre([pformat(sys.path)]),
                      html.H2("os.environ"),
                      html.Pre([pformat(dict(os.environ))])
        ])])
        msg = self._transform(title, body, environ)
        return self._return_response(msg, start_response,
                                     status="500 Internal Server Error",
                                     contenttype="text/html")

    def _transform(self, title, body, environ, template="xsl/error.xsl"):
        fakerepo = self.repos[0]
        doc = fakerepo.make_document()
        doc.uri = request_uri(environ)
        doc.meta.add((URIRef(doc.uri),
                      DCTERMS.title,
                      Literal(title, lang="sv")))
        doc.body = body
        xhtml = fakerepo.render_xhtml_tree(doc)
        conffile = os.sep.join([self.config.documentroot, 'rsrc',
                                'resources.xml'])
        transformer = Transformer('XSLT', template, "xsl",
                                  resourceloader=fakerepo.resourceloader,
                                  config=conffile)
        urltransform = None
        if 'develurl' in self.config:
            urltransform = fakerepo.get_url_transform_func(
                develurl=self.config.develurl)
        depth = len(doc.uri.split("/")) - 3
        tree = transformer.transform(xhtml, depth,
                                     uritransform=urltransform)
        return etree.tostring(tree, encoding="utf-8")
        
        

    ################################################################
    # API Helper methods
    def stats(self, resultset=()):
        slices = OrderedDict()

        datadict = defaultdict(list)

        # 1: Create a giant RDF graph consisting of all triples of all
        #    repos' commondata. To avoid parsing the same RDF files
        #    over and over, this section duplicates the logic of
        #    DocumentRepository.commondata to make sure each RDF
        #    file is loaded only once.
        ttlfiles = set()
        resource_graph = Graph()
        namespaces = {}
        for repo in self.repos:
            for prefix, ns in repo.make_graph().namespaces():
                assert ns not in namespaces or namespaces[ns] == prefix, "Conflicting prefixes for ns %s" % ns
                namespaces[ns] = prefix
                resource_graph.bind(prefix, ns)
                for cls in inspect.getmro(repo.__class__):
                    if hasattr(cls, "alias"):
                        commonpath = "res/extra/%s.ttl" % cls.alias
                        if os.path.exists(commonpath):
                            ttlfiles.add(commonpath)
                        elif pkg_resources.resource_exists('ferenda', commonpath):
                            ttlfiles.add(pkg_resources.resource_filename('ferenda', commonpath))

        self.log.debug("stats: Loading resources %s into a common resource graph" %
                       list(ttlfiles))
        for filename in ttlfiles:
            resource_graph.parse(data=util.readfile(filename), format="turtle")
        pkg_resources.cleanup_resources()


        # 2: if used in the resultset mode, only calculate stats for those
        # resources/documents that are in the resultset.
        resultsetmembers = set()
        if resultset:
            for r in resultset:
                resultsetmembers.add(r['iri'])

        # 3: using each repo's faceted_data and its defined facet
        # selectors, create a set of observations for that repo
        # 
        # FIXME: If in resultset mode, we might ask a repo for its
        # faceted data and then use exactly none of it since it
        # doesn't match anything in resultsetmembers. We COULD analyze
        # common resultset iri prefixes and then only call
        # faceted_data for some (or one) repo.
        for repo in self.repos:
            data = repo.faceted_data()
            if resultsetmembers:
                data = [r for r in data if r['uri'] in resultsetmembers]

            for facet in repo.facets():
                if not facet.dimension_type:
                    continue
                dimension, obs = self.stats_slice(data, facet, resource_graph)
                if dimension in slices:
                    # since observations is a Counter not a regular
                    # dict, if slices[dimensions] and observations
                    # have common keys this will add the counts not
                    # replace them.
                    slices[dimension].update(obs)
                else:
                    slices[dimension] = obs

        # 4. Transform our easily-updated data structures to the list
        # of dicts of lists that we're supposed to return.
        res = {"type": "DataSet",
               "slices": []
               }
        for k, v in sorted(slices.items()):
            observations = []
            for ok, ov in sorted(v.items()):
                observations.append({ok[0]: ok[1],
                                     "count": ov})
            res['slices'].append({"dimension": k,
                                  "observations": observations})
        return res

    def stats_slice(self, data, facet, resource_graph):
        binding = resource_graph.qname(facet.rdftype).replace(":", "_")
        if facet.dimension_label:
            dimension_label = facet.dimension_label
        elif self.config.legacyapi:
            dimension_label = util.uri_leaf(str(facet.rdftype))
        else:
            dimension_label = binding

        dimension_type = facet.dimension_type
        if (self.config.legacyapi and
                dimension_type == "value"):
            # legacyapi doesn't support the value type, we must
            # convert it into ref, and convert all string values to
            # fake resource ref URIs
            dimension_type = "ref"
            transformer = lambda x: (
                "http://example.org/fake-resource/%s" %
                x).replace(
                " ",
                "_")
        elif self.config.legacyapi and dimension_type == "term":
            # legacyapi expects "Standard" over "bibo:Standard", which is what
            # Facet.qname returns
            transformer = lambda x: x.split(":")[1]
        else:
            transformer = lambda x: x

        observations = Counter()
        # one file per uri+observation seen -- avoid
        # double-counting
        observed = {}
        for row in data:
            observation = None
            try:
                # maybe if facet.dimension_type == "ref", selector
                # should always be Facet.defaultselector?  NOTE:
                # we look at facet.dimension_type, not
                # dimension_type, as the latter may be altered if
                # legacyapi == True
                if facet.dimension_type == "ref":
                    observation = transformer(Facet.defaultselector(
                        row, binding))
                else:
                    observation = transformer(
                        facet.selector(
                            row,
                            binding,
                            resource_graph))

            except Exception as e:
                # most of the time, we should swallow this
                # exception since it's a selector that relies on
                # information that is just not present in the rows
                # from some repos. I think.
                if hasattr(facet.selector, 'im_self'):
                    # try to find the location of the selector
                    # function for easier debugging
                    fname = "%s.%s.%s" % (facet.selector.__module__,
                                          facet.selector.im_self.__name__,
                                          facet.selector.__name__)
                else:
                    # probably a lambda function
                    fname = facet.selector.__name__
                # FIXME: do we need the repo name here to provide useful
                # messages?
                # self.log.warning("facet %s (%s) fails for row %s : %s %s" % (binding, fname, row['uri'], e.__class__.__name__, str(e)))

                pass
            if observation is not None:
                k = (dimension_type, observation)
                if (row['uri'], observation) not in observed:
                    observed[(row['uri'], observation)] = True
                    observations[k] += 1
        return dimension_label, observations

    def query(self, environ):
        # this is needed -- but the connect call shouldn't neccesarily
        # have to call exists() (one HTTP call)
        idx = FulltextIndex.connect(self.config.indextype,
                                    self.config.indexlocation,
                                    self.repos)
        q, param, pagenum, pagelen, stats = self.parse_parameters(
            environ['QUERY_STRING'], idx)
        ac_query = environ['QUERY_STRING'].endswith("_ac=true")
        exclude_types = environ.get('exclude_types', None)
        boost_types = environ.get('boost_types', None)
        res, pager = idx.query(q=q,
                               pagenum=pagenum,
                               pagelen=pagelen,
                               ac_query=ac_query,
                               exclude_types=exclude_types,
                               boost_types=boost_types,
                               **param)
        mangled = self.mangle_results(res, ac_query)
        # 3.1 create container for results
        res = {"startIndex": pager['firstresult'] - 1,
               "itemsPerPage": int(param.get('_pageSize', '10')),
               "totalResults": pager['totalresults'],
               "duration": None,  # none
               "current": environ['PATH_INFO'] + "?" + environ['QUERY_STRING'],
               "items": mangled}

        # 4. add stats, maybe
        if stats:
            res["statistics"] = self.stats(mangled)
        return res


    def mangle_results(self, res, ac_query):
        def _elements_to_html(elements):
            res = ""
            for e in elements:
                if isinstance(e, str):
                    res += e
                else:
                    res += '<em class="match">%s</em>' % str(e)
            return res

        # Mangle res into the expected JSON structure (see qresults.json)
        if ac_query:
            # when doing an autocomplete query, we want the relevance order from ES
            hiterator = res
        else:
            # for a regular API query, we need another order (I forgot exactly why...)
            hiterator = sorted(res, key=itemgetter("uri"), reverse=True)
        mangled = []
        for hit in hiterator:
            mangledhit = {}
            for k, v in hit.items():
                if self.config.legacyapi:
                    if "_" in k:
                        # drop prefix (dcterms_issued -> issued)
                        k = k.split("_", 1)[1]
                    elif k == "innerhits":
                        continue  # the legacy API has no support for nested/inner hits
                if k == "uri":
                    k = "iri"
                    # change eg https://lagen.nu/1998:204 to
                    # http://localhost:8080/1998:204 during
                    # development
                    if v.startswith(self.config.url) and self.config.develurl:
                        v = v.replace(self.config.url, self.config.develurl)
                if k == "text":
                    mangledhit["matches"] = {"text": _elements_to_html(hit["text"])}
                elif k in ("basefile", "repo"):
                    # these fields should not be included in results
                    pass
                else:
                    mangledhit[k] = v
            mangledhit = self.mangle_result(mangledhit, ac_query)
            mangled.append(mangledhit)
        return mangled

    def mangle_result(self, hit, ac_query=False):
        return hit

    def parse_parameters(self, querystring, idx):
        def _guess_real_fieldname(k, schema):
            for fld in schema:
                if fld.endswith(k):
                    return fld
            raise KeyError(
                "Couldn't find anything that endswith(%s) in fulltextindex schema" %
                k)

        if isinstance(querystring, bytes):
            # Assume utf-8 encoded URL -- when is this assumption
            # incorrect?
            querystring = querystring.decode("utf-8")

        param = dict(parse_qsl(querystring))
        filtered = dict([(k, v)
                         for k, v in param.items() if not (k.startswith("_") or k == "q")])
        if filtered:
            # OK, we have some field parameters. We need to get at the
            # current schema to know how to process some of these and
            # convert them into fulltextindex.SearchModifier objects
            
            # Range: some parameters have additional parameters, eg
            # "min-dcterms_issued=2014-01-01&max-dcterms_issued=2014-02-01"
            newfiltered = {}
            for k, v in list(filtered.items()):
                if k.startswith("min-") or k.startswith("max-"):
                    op = k[:4]
                    compliment = k.replace(op, {"min-": "max-",
                                                "max-": "min-"}[op])
                    k = k[4:]
                    if compliment in filtered:
                        start = filtered["min-" + k]
                        stop = filtered["max-" + k]
                        newfiltered[k] = fulltextindex.Between(datetime.strptime(start, "%Y-%m-%d"),
                                                               datetime.strptime(stop, "%Y-%m-%d"))
                    else:
                        cls = {"min-": fulltextindex.More,
                               "max-": fulltextindex.Less}[op]
                        # FIXME: need to handle a greater variety of str->datatype conversions
                        v = datetime.strptime(v, "%Y-%m-%d")
                        newfiltered[k] = cls(v)
                elif k.startswith("year-"):
                    # eg for year-dcterms_issued=2013, interpret as
                    # Between(2012-12-31 and 2014-01-01)
                    k = k[5:]
                    newfiltered[k] = fulltextindex.Between(date(int(v) - 1, 12, 31),
                                                           date(int(v) + 1, 1, 1))
                else:
                    newfiltered[k] = v
            filtered = newfiltered

            schema = idx.schema()
            if self.config.legacyapi:
                # 2.3 legacyapi requires that parameters do not include
                # prefix. Therefore, transform publisher.iri =>
                # dcterms_publisher (ie remove trailing .iri and append a
                # best-guess prefix
                newfiltered = {}
                for k, v in filtered.items():
                    if k.endswith(".iri"):
                        k = k[:-4]
                        # the parameter *looks* like it's a ref, but it should
                        # be interpreted as a value -- remove starting */ to
                        # get at actual querystring

                        # FIXME: in order to lookup k in schema, we may need
                        # to guess its prefix, but we're cut'n pasting the
                        # strategy from below. Unify.
                        if k not in schema and "_" not in k and k not in ("uri"):
                            k = _guess_real_fieldname(k, schema)

                        if v.startswith(
                                "*/") and not isinstance(schema[k], fulltextindex.Resource):
                            v = v[2:]
                    if k not in schema and "_" not in k and k not in ("uri"):
                        k = _guess_real_fieldname(k, schema)
                        newfiltered[k] = v
                    else:
                        newfiltered[k] = v
                filtered = newfiltered

            # 2.1 some values need to be converted, based upon the
            # fulltextindex schema.
            # if schema[k] == fulltextindex.Datetime, do strptime.
            # if schema[k] == fulltextindex.Boolean, convert 'true'/'false' to True/False.
            # if k = "rdf_type" and v looks like a qname or termname, expand v
            for k, fld in schema.items():
                # NB: Some values might already have been converted previously!
                if k in filtered and isinstance(filtered[k], str):
                    if isinstance(fld, fulltextindex.Datetime):
                        filtered[k] = datetime.strptime(filtered[k], "%Y-%m-%d")
                    elif isinstance(fld, fulltextindex.Boolean):
                        filtered[k] = (filtered[k] == "true")  # only "true" is True
                    elif k == "rdf_type" and re.match("\w+:[\w\-_]+", filtered[k]):
                        # expand prefix ("bibo:Standard" -> "http://purl.org/ontology/bibo/")
                        (prefix, term) = re.match("(\w+):([\w\-_]+)", filtered[k]).groups()
                        for repo in self.repos:
                            if prefix in repo.ns:
                                filtered[k] = str(repo.ns[prefix]) + term
                                break
                        else:
                            self.log.warning("Can't map %s to full URI" % (filtered[k]))
                        pass
                    elif k == "rdf_type" and self.config.legacyapi and re.match("[\w\-\_]+", filtered[k]):
                        filtered[k] = "*" + filtered[k]

        q = param['q'] if 'q' in param else None

        # find out if we need to get all results (needed when stats=on) or
        # just the first page
        if param.get("_stats") == "on":
            pagenum = 1
            pagelen = 10000 # this is the max that default ES 2.x will allow
            stats = True
        else:
            pagenum = int(param.get('_page', '0')) + 1
            pagelen = int(param.get('_pageSize', '10'))
            stats = False

        return q, filtered, pagenum, pagelen, stats

    def _search_parse_query(self, querystring):
        # FIXME: querystring should probably be sanitized before
        # calling .query() - but in what way?
        queryparams = OrderedDict(parse_qsl(querystring))
        return queryparams
    
    def _search_run_query(self, queryparams, boost_types=None):
        idx = FulltextIndex.connect(self.config.indextype,
                                    self.config.indexlocation,
                                    self.repos)
        query = queryparams.get('q')
        if isinstance(query, bytes):  # happens on py26
            query = query.decode("utf-8")  # pragma: no cover
#        query += "*"  # we use a simple_query_string query by default,
#                      # and we probably want to do a prefix query (eg
#                      # "personuppgiftslag" should match a label field
#                      # containing "personuppgiftslag (1998:204)",
#                      # therefore the "*"
#
#        # maybe not, though -- seems to conflict with
#        # stemming/indexing, ie "bulvanutredningen*" doesn't match the
#        # indexed "bulvanutredningen" (which has been stemmed to
#        # "bulvanutredning"
        pagenum = int(queryparams.get('p', '1'))
        qpcopy = dict(queryparams)
        for x in ('q', 'p'):
            if x in qpcopy:
                del qpcopy[x]
        res, pager = idx.query(query, pagenum=pagenum, boost_types=boost_types, **qpcopy)
        return res, pager


    def _search_render_pager(self, pager, queryparams, path_info):
        # Create some HTML code for the pagination. FIXME: This should
        # really be in search.xsl instead
        pages = []
        pagenum = pager['pagenum']
        startpage = max([0, pager['pagenum'] - 4])
        endpage = min([pager['pagecount'], pager['pagenum'] + 3])
        if startpage > 0:
            queryparams['p'] = str(pagenum - 2)
            url = path_info + "?" + urlencode(queryparams)
            pages.append(html.LI([html.A(["«"], href=url)]))

        for pagenum in range(startpage, endpage):
            queryparams['p'] = str(pagenum + 1)
            url = path_info + "?" + urlencode(queryparams)
            attrs = {}
            if pagenum + 1 == pager['pagenum']:
                attrs['class'] = 'active'
            pages.append(html.LI([html.A([str(pagenum + 1)], href=url)],
                                 **attrs))

        if endpage < pager['pagecount']:
            queryparams['p'] = str(pagenum + 2)
            url = path_info + "?" + urlencode(queryparams)
            pages.append(html.LI([html.A(["»"], href=url)]))

        return html.UL(pages, **{'class': 'pagination'})
    
    def _str(self, s, encoding="ascii"):
        """If running under python2, return byte string version of the
        argument, otherwise return the argument unchanged.

        Needed since wsgiref under python 2 hates unicode.

        """
        if sys.version_info < (3, 0, 0):
            return s.encode("ascii")  # pragma: no cover
        else:
            return s
