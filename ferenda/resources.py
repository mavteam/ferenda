# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import *

from io import BytesIO
import inspect
import json
import logging
import os

from lxml import etree
from lxml.builder import ElementMaker
from rdflib import URIRef, Literal, BNode, Graph, Namespace, RDF, RDFS
from rdflib.namespace import FOAF, SKOS
BIBO = Namespace("http://purl.org/ontology/bibo/")
from layeredconfig import LayeredConfig, Defaults

from ferenda import DocumentRepository, ResourceLoader
from ferenda import util, errors

class Resources(object):

    """Creates and manages various assets/resources needed for web serving.
    """

    def __init__(self, repos, resourcedir, **kwargs):
        # FIXME: document what kwargs could be (particularly 'combineresources')
        self.repos = repos
        self.resourcedir = resourcedir
        from ferenda.manager import DEFAULT_CONFIG
        defaults = dict(DEFAULT_CONFIG)
        defaults.update(DocumentRepository.get_default_options())
        defaults.update(kwargs)
        self.config = LayeredConfig(Defaults(defaults))
        # the below call to setup_logger alters the logging level of
        # the root logger, which can't be good practice. Also, we
        # should probably not log to the root logger, but rather to
        # ferenda.resources.
        #
        # from ferenda.manager import setup_logger
        # self.log = setup_logger()
        self.log = logging.getLogger("ferenda.resources")
        # FIXME: How should we set up a global loadpath from the
        # individual repos?
        loadpaths = [ResourceLoader.make_loadpath(repo) for repo in repos]
        loadpath = ["."]  # cwd always has priority -- makes sense?
        for subpath in loadpaths:
            for p in subpath:
                if p not in loadpath:
                    loadpath.append(p)
        self.resourceloader = ResourceLoader(*loadpath)

    def make(self,
             css=True,
             js=True,
             img=True,
             xml=True,
             api=None):
        res = {}
        if api is None:
            api = not self.config.staticsite
        if css:
            res['css'] = self.make_css()
        if js:
            res['js'] = self.make_js()
        if img:
            res['img'] = self.make_img()
        if xml:
            res['xml'] = self.make_resources_xml(res.get('css', []), res.get('js', []))
        if api:
            res['json'] = self.make_api_files()

        # finally, normalize paths according to os.path.sep
        # conventions
        if os.sep == "\\":
            for part in res:
                result = []
                for x in res[part]:
                    if x.startswith("http://") or x.startswith("https://"):
                        result.append(x)
                    else:
                        result.append(x.replace('/', os.sep))
                res[part] = result
        return res

    def make_css(self):
        import cssmin
        combinefile = None
        if self.config.combineresources:
            combinefile = os.sep.join([self.resourcedir, 'css', 'combined.css'])
        return self._make_files(
            'cssfiles', self.resourcedir + os.sep + 'css', combinefile, cssmin.cssmin)

    def make_js(self):
        # slimit provides better perf, but isn't py3 compatible
        # import slimit
        # js = slimit.minify(
        #     jsbuffer.getvalue(), mangle=True, mangle_toplevel=True)
        import jsmin
        combinefile = None
        if self.config.combineresources:
            combinefile = os.sep.join([self.resourcedir, 'js', 'combined.js'])
        return self._make_files(
            'jsfiles', self.resourcedir + os.sep + 'js', combinefile, jsmin.jsmin)

    def make_img(self):
        return self._make_files('imgfiles', self.resourcedir + os.sep + 'img')

    def make_resources_xml(self, cssfiles, jsfiles):
        E = ElementMaker()  # namespace = None, nsmap={None: ...}
        root = E.configuration(
            E.sitename(self.config.sitename),
            E.sitedescription(self.config.sitedescription),
            E.url(self.config.url),
            E.tabs(*self._links('tabs')),
            E.footerlinks(*self._links('footer')),
            E.stylesheets(*self._li_wrap(cssfiles, 'link', 'href', rel="stylesheet")),
            E.javascripts(*self._li_wrap(jsfiles, 'script', 'src', text=" "))
        )

        if not self.config.staticsite:
            root.append(
                E.search(
                    E.endpoint(self.config.searchendpoint)
                )
            )

        outfile = self.resourcedir + os.sep + "resources.xml"
        util.writefile(
            outfile,
            etree.tostring(
                root,
                encoding="utf-8",
                pretty_print=True).decode("utf-8"))
        self.log.info("Wrote %s" % outfile)
        return [self._filepath_to_urlpath(outfile, 1)]

    # FIXME: When creating <script> elements, must take care not to
    # create self-closing tags (like by creating a single space text
    # node)
    def _li_wrap(self, items, container, attribute, text=None, **kwargs):
        elements = []
        for item in items:
            kwargs[attribute] = item
            e = etree.Element(container, **kwargs)
            e.text = text
            elements.append(e)
        return elements

    def _links(self, methodname):
        E = ElementMaker()
        elements = []
        for repo in self.repos:
            alias = repo.alias
            items = getattr(repo, methodname)()
            self.log.debug("Adding %(methodname)s from docrepo %(alias)s" %
                           locals())
            elements.extend(self._links_listitems(items))
        return elements

    def _links_listitems(self, listitems):
        E = ElementMaker()
        elements = []
        for item in listitems:
            if len(item) == 2:
                (label, url) = item
                sublists = None
            else:
                (label, url, sublists) = item
            self.log.debug(
                " - %(label)s (%(url)s)" % locals())
            if url:
                li = E.li(E.a({'href': url}, label))
            else:
                li = E.li(label)
            if sublists:
                subelements = []
                for sublist in sublists:
                    subelements.extend(self._links_listitems(sublist))
                li.append(E.ul(*subelements))
            elements.append(li)
        return elements

    def _make_files(self, option, filedir, combinefile=None, combinefunc=None):
        urls = []
        buf = BytesIO()
        processed = set()
        # eg. self.config.cssfiles
        if getattr(self.config, option):  # it's possible to set eg
                                          # cssfiles=None when
                                          # creating the Resources
                                          # object
            for f in getattr(self.config, option):
                urls.append(self._process_file(f, buf, filedir, "ferenda.ini"))
                processed.add(f)
        for repo in self.repos:
            # FIXME: create a more generic way of optionally
            # signalling to a repo that "Hey, now it's time to create
            # your resources if you can"
            if repo.__class__.__name__ == "SFS" and option == "imgfiles":
                self.log.info("calling into SFS._makeimages()")
                LayeredConfig.set(repo.config, 'imgfiles', repo._makeimages())
            if hasattr(repo.config, option):
                for f in getattr(repo.config, option):
                    if f in processed:
                        continue
                    urls.append(self._process_file(f, buf, filedir, repo.alias))
                    processed.add(f)
        urls = list(filter(None, urls))
        if combinefile:
            txt = buf.getvalue().decode('utf-8')
            util.writefile(combinefile, combinefunc(txt))
            return [self._filepath_to_urlpath(combinefile, 2)]
        else:
            return urls

    def _process_file(self, filename, buf, destdir, origin=""):
        """
        Helper function to concatenate or copy CSS/JS (optionally
        processing them with e.g. Scss) or other files to correct place
        under the web root directory.

        :param filename: The name (relative to the ferenda package) of the file
        :param buf: A buffer into which the contents of the file is written
                    (if combineresources == True)
        :param destdir: The directory into which the file will be copied
                        (unless combineresources == True)
        :param origin: The source of the configuration that specifies this file
        :returns: The URL path of the resulting file, relative to the web root
                  (or None if combineresources == True)
        :rtype: str
        """
        if filename.startswith("http://") or filename.startswith("https://"):
            if self.config.combineresources:
                raise errors.ConfigurationError(
                    "makeresources: Can't use combineresources=True in combination with external js/css URLs (%s)" % filename)
            self.log.debug("Using external url %s" % filename)
            return filename
        try: 
            fp = self.resourceloader.openfp(filename, binary=True)
        except errors.ResourceNotFound:
            self.log.warning("file %(filename)s (specified in %(origin)s)"
                             " doesn't exist" % locals())
            return None

        (base, ext) = os.path.splitext(filename)

        if self.config.combineresources:
            self.log.debug("combining %s into buffer" % filename)
            d = fp.read()
            buf.write(d)
            fp.close()
            return None
        else:
            # FIXME: don't copy (at least not log) if the outfile
            # already exists.
            # self.log.debug("writing %s out to %s" % (filename, destdir))
            outfile = destdir + os.sep + os.path.basename(filename)
            if (os.path.islink(outfile) and
                os.path.relpath(os.path.join(os.path.dirname(outfile),
                                             os.readlink(outfile))) == util.name_from_fp(fp)):
                self.log.warning("%s is a symlink to source file %s, won't overwrite" % (outfile, util.name_from_fp(fp)))
            else:
                util.ensure_dir(outfile)
                with open(outfile, "wb") as fp2:
                    fp2.write(fp.read())
                fp.close()
            return self._filepath_to_urlpath(outfile, 2)

    def make_api_files(self):
        # this should create the following files under resourcedir
        # api/context.json (aliased to /json-ld/context.json if legacyapi)
        # api/terms.json (aliased to /var/terms.json if legacyapi)
        # api/common.json (aliased to /var/common.json if legacyapi)
        # MAYBE api/ui/  - copied from ferenda/res/ui
        files = []
        context = os.sep.join([self.resourcedir, "api", "context.json"])
        if self.config.legacyapi:
            self.log.info("Creating API files for legacyapi")
            contextpath = "/json-ld/context.json"
            termspath = "/var/terms"
            commonpath = "/var/common"
        else:
            # FIXME: create correct URL path
            contextpath = "/rsrc/api/context.json"
            termspath = "/rsrc/api/terms.json"
            commonpath = "/rsrc/api/common.json"
        util.ensure_dir(context)
        with open(context, "w") as fp:
            contextdict = self._get_json_context()
            s = json.dumps({"@context": contextdict}, separators=(', ', ': '),
                           indent=4, sort_keys=True)
            fp.write(s)
        files.append(self._filepath_to_urlpath(context, 2))

        common = os.sep.join([self.resourcedir, "api", "common.json"])
        terms = os.sep.join([self.resourcedir, "api", "terms.json"])

        for (filename, func, urlpath) in ((common, self._get_common_graph, commonpath),
                                          (terms,  self._get_term_graph,   termspath)):
            g = func(self.config.url + urlpath[1:])
            d = json.loads(g.serialize(format="json-ld", context=contextdict,
                                       indent=4).decode("utf-8"))
            # d might not contain a @context (if contextdict == {}, ie
            # no repos are given)
            if '@context' in d:
                d['@context'] = contextpath
            if self.config.legacyapi:
                d = self._convert_legacy_jsonld(d, self.config.url + urlpath[1:])
            with open(filename, "w") as fp:
                s = json.dumps(d, indent=4, separators=(', ', ': '), sort_keys=True)
                fp.write(s)
                
            files.append(self._filepath_to_urlpath(filename, 2))

        if self.config.legacyapi:
            # copy ui explorer app to <url>/rsrc/ui/ -- this does not get
            # included in files
            targetdir = os.sep.join([self.resourcedir, "ui"])
            self.resourceloader.extractdir("ui", targetdir)
        return files

    def _convert_legacy_jsonld(self, indata, rooturi):
        # the json structure should be a top node containing only
        # @context, iri (localhost:8000/var/terms), type (foaf:Document)
        # and topic - a list of dicts, where each dict looks like:
        #
        # {"iri" : "referatserie",
        #  "comment" : "Anger vilken referatserie som referatet eventuellt tillhör.",
        #  "label" : "Referatserie",
        #  "type" : "DatatypeProperty"}
        out = {}
        topics = []

        # the property containing the id/uri for the
        # record may be under @id or iri, depending on
        # whether self.config.legacyapi was in effect for
        # _get_json_context()
        if self.config.legacyapi:
            idfld = 'iri'
        else:
            idfld = '@id'

        # indata might be a mapping containing a list of mappings
        # under @graph, or it might just be the actual list.
        wantedlist = None
        if isinstance(indata, list):
            wantedlist = indata
        else:
            for topkey, topval in indata.items():
                if topkey == "@graph":
                    wantedlist = topval
                    break

        if not wantedlist:
            self.log.warning(
                "Couldn't find list of mappings in %s, topics will be empty" %
                indata)
        else:
            shortened = {}
            for subject in sorted(wantedlist, key=lambda x: x["iri"]):
                if subject[idfld] == rooturi:
                    for key, value in subject.items():
                        if key in (idfld, 'foaf:topic'):
                            continue
                        out[key] = value
                else:
                    for key in subject:
                        if isinstance(subject[key], list):
                            # make sure multiple values are sorted for
                            # the same reason as below
                            subject[key].sort()

                    # FIXME: We want to use just the urileaf for
                    # legacyapi clients (ie Standard instead of
                    # bibo:Standard) but to be proper json-ld, this
                    # requires that we define contexts for this. Which
                    # we don't (yet)
                    if ("iri" in subject and
                            ":" in subject["iri"] and
                            "://" not in subject["iri"]):
                        short = subject["iri"].split(":", 1)[1]
                        if short in shortened:
                            self.log.warning(
                                "Cannot shorten IRI %s -> %s, already defined (%s)" %
                                (subject["iri"], short, shortened[short]))
                            del subject["iri"]  # skips adding this to topics
                        else:
                            shortened[short] = subject["iri"]
                            subject["iri"] = short
                    if "iri" in subject and subject["iri"]:
                        topics.append(subject)

        # make sure the triples are in a predictable order, so we can
        # compare on the JSON level for testing
        out['topic'] = sorted(topics, key=lambda x: x[idfld])
        out['iri'] = rooturi
        if '@context' in indata:
            out['@context'] = indata['@context']
        return out

    def _get_json_context(self):
        data = {}
        # step 1: define all prefixes
        for repo in self.repos:
            for (prefix, ns) in repo.ns.items():
                if prefix in data:
                    assert data[prefix] == str(
                        ns), "Conflicting URIs for prefix %s" % prefix
                else:
                    data[prefix] = str(ns)

        # foaf and rdfs must always be defined prefixes
        data["foaf"] = "http://xmlns.com/foaf/0.1/"
        data["rdfs"] = "http://www.w3.org/2000/01/rdf-schema#"

        # the legacy api client expects some terms to be available using
        # shortened forms (eg 'label' instead of 'rdfs:label'), so we must
        # define them in our context
        if self.config.legacyapi:
            data['iri'] = "@id"
            data['type'] = "@type"
            data['label'] = 'rdfs:label'
            data['name'] = 'foaf:name'
            data['altLabel'] = 'skos:altLabel'
            # data["@language"] = "en" # how to set this? majority vote of
            # repos / documents? note that it's
            # only a default.
        return data

    def _get_term_graph(self, graphuri):
        # produce a rdf graph of the terms (classes and properties) in
        # the vocabs we're using. This should preferably entail
        # loading the vocabularies (stored as RDF/OWL documents), and
        # expressing all the things that are owl:*Property, owl:Class,
        # rdf:Property and rdf:Class. As an intermediate step, we
        # could have preprocessed rdf graphs (stored in
        # res/vocab/dcterms.ttl, res/vocab/bibo.ttl etc) derived from the
        # vocabularies and pull them in like we pull in namespaces in
        # self.ns The rdf graph should be rooted in an url (eg
        # http://localhost:8080/var/terms, and then have each term as
        # a foaf:topic. Each term should be described with its
        # rdf:type, rdfs:label (most important!) and possibly
        # rdfs:comment
        root = URIRef(graphuri)
        g = Graph()
        g.add((root, RDF.type, FOAF.Document))
        bigg = Graph()
        paths = set()
        for repo in self.repos:
            for p, ns in repo.ns.items():
                if p in ("rdf", "rdfs", "owl"):
                    continue
                g.bind(p, ns)
                resourcename = "vocab/%s.ttl" % p
                if repo.resourceloader.exists(resourcename):
                    ontopath = repo.resourceloader.filename(resourcename)
                    if ontopath not in paths:
                        self.log.debug("Loading vocabulary %s" % ontopath)
                        with open(ontopath) as onto:
                            bigg.parse(onto, format="turtle")
                        paths.add(ontopath)

        g.bind("foaf", "http://xmlns.com/foaf/0.1/")
        for (s, p, o) in bigg:
            if p in (RDF.type, RDFS.label, RDFS.comment):
                if isinstance(s, BNode): # occurs in the def of foaf:member
                    continue 
                g.add((root, FOAF.topic, s))  # unless we've already added it?
                if isinstance(o, Literal):  # remove language typing info
                    o = Literal(str(o))
                g.add((s, p, o))  # control duplicates somehow
        return g

    def _get_common_graph(self, graphuri):
        # create a graph with foaf:names for all entities (publishers,
        # publication series etc) that our data mentions.
        root = URIRef(graphuri)
        g = Graph()
        g.bind("skos", SKOS)
        g.bind("foaf", FOAF)
        g.add((root, RDF.type, FOAF.Document))
        paths = set()
        bigg = Graph()
        for repo in self.repos:
            for cls in inspect.getmro(repo.__class__):
                if hasattr(cls, "alias"):
                    resourcename = "extra/%s.ttl" % cls.alias
                    if repo.resourceloader.exists(resourcename):
                        commonpath = repo.resourceloader.filename(resourcename)
                        if commonpath not in paths:
                            self.log.debug("loading data %s" % commonpath)
                            with open(commonpath) as common:
                                bigg.parse(common, format="turtle")
                            paths.add(commonpath)
        for (s, p, o) in bigg:
            if p in (FOAF.name, SKOS.prefLabel,
                     SKOS.altLabel, BIBO.identifier):
                g.add((root, FOAF.topic, s))
                # strip any typing/langtagging (because of reasons)
                if isinstance(o, Literal):
                    o = Literal(str(o))
                g.add((s, p, o))
                # try to find a type
                g.add((s, RDF.type, bigg.value(s, RDF.type)))
        return g

    def _filepath_to_urlpath(self, path, keep_segments=2):
        """
        :param path: the full or relative filepath to transform into a urlpath
        :param keep_segments: the number of directory segments to keep (the ending filename is always kept)
        """
        # data/repo/rsrc/js/main.js, 3 -> repo/rsrc/js/main.js
        # /var/folders/tmp4q6b1g/rsrc/resources.xml, 1 -> rsrc/resources.xml
        # C:\docume~1\owner\locals~1\temp\tmpgbyuk7\rsrc\css\test.css, 2 - rsrc/css/test.css
        path = path.replace(os.sep, "/")
        urlpath = "/".join(path.split("/")[-(keep_segments + 1):])
        # print("_filepath_to_urlpath (%s): %s -> %s" % (keep_segments, path, urlpath))
        return urlpath
