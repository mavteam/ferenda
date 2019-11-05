# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import *

# From python stdlib
import re
import os
from datetime import datetime, timedelta

# 3rd party modules
import lxml.html
import requests
from rdflib import Literal, URIRef
from rdflib.namespace import SKOS, XSD, DCTERMS, FOAF
from bs4 import BeautifulSoup

# My own stuff
from ferenda import FSMParser, DocumentEntry
from ferenda import decorators, util
from ferenda.elements import Body, Paragraph
from ferenda.errors import DownloadError
from . import RPUBL
from .fixedlayoutsource import FixedLayoutSource, FixedLayoutStore
from .swedishlegalsource import UnorderedSection
from .elements import *


class JOStore(FixedLayoutStore):
    def basefile_to_pathfrag(self, basefile):
        # store data using years as top-level dir, even though the
        # diarienummer are constructed the other way round.
        #
        # "1000-2004" => "2004/1000"
        # "6356-2012" => "2012/6356"
        if "-" not in basefile:
            return super(JOStore, self).basefile_to_pathfrag(basefile)
        no, year = basefile.split("-")
        return "%s/%s" % (year, no)

    def pathfrag_to_basefile(self, pathfrag):
        # "2004/1000" => "1000-2004"
        # "2012/6356" => "6356-2012"
        year, no = pathfrag.split(os.sep)
        return "%s-%s" % (no, year)

class JO(FixedLayoutSource):

    """Hanterar beslut från Riksdagens Ombudsmän, www.jo.se

    Modulen hanterar hämtande av beslut från JOs webbplats i PDF samt
    omvandlande av dessa till XHTML.

    """
    alias = "jo"
    start_url = "http://www.jo.se/sv/JO-beslut/Soka-JO-beslut/?query=*&pn=1"
    document_url_regex = "http://www.jo.se/PageFiles/(?P<dummy>\d+)/(?P<basefile>\d+\-\d+)(?P<junk>[,%\d\-]*).pdf"
    headnote_url_template = "http://www.jo.se/sv/JO-beslut/Soka-JO-beslut/?query=%(basefile)s&pn=1"
    # headnote_url_template = "http://www.jo.se/sv/JO-beslut/Soka-JO-beslut/?query=%(basefile)s&caseNumber=%(basefile)s"
    rdf_type = RPUBL.VagledandeMyndighetsavgorande
    storage_policy = "dir"
    downloaded_suffix = ".pdf"
    documentstore_class = JOStore
    urispace_segment = "avg/jo"
    xslt_template = "xsl/avg.xsl"
    sparql_annotations = "sparql/avg-annotations.rq"
    sparql_expect_results = False

    def metadata_from_basefile(self, basefile):
        attribs = super(JO, self).metadata_from_basefile(basefile)
        attribs["rpubl:diarienummer"] = basefile
        attribs["dcterms:publisher"] = self.lookup_resource(
                    'JO', SKOS.altLabel)
        return attribs

    @decorators.action
    @decorators.recordlastdownload
    def download(self, basefile=None, url=None):
        if basefile:
            if not url:
                entry = DocumentEntry(self.store.documententry_path(basefile))
                url = entry.orig_url
            if url:
                return self.download_single(basefile, url)
            else:
                raise DownloadError("%s doesn't support downloading single basefiles w/o page URL" %
                                    self.__class__.__name__)
        self.session = requests.session()
        if ('lastdownload' in self.config and
                self.config.lastdownload and
                not self.config.refresh):
            startdate = self.config.lastdownload - timedelta(days=30)
            self.start_url += "&from=%s" % datetime.strftime(startdate, "%Y-%m-%d")
        for basefile, url in self.download_get_basefiles(self.start_url):
            self.download_single(basefile, url)

    @decorators.downloadmax
    def download_get_basefiles(self, start_url):
        # FIXME: try to download a single result HTML page, since
        # there are a few metadata props there.
        done = False
        url = start_url
        pagecount = 1
        self.log.debug("Starting at %s" % start_url)
        while not done:
            nextpage = None
            assert "pn=%s" % pagecount in url
            soughtnext = url.replace("pn=%s" % pagecount,
                                     "pn=%s" % (pagecount + 1))
            self.log.debug("Getting page #%s" % pagecount)
            resp = requests.get(url)
            tree = lxml.html.document_fromstring(resp.text)
            tree.make_links_absolute(url, resolve_base_href=True)
            for element, attribute, link, pos in tree.iterlinks():
                m = re.match(self.document_url_regex, link)
                if m:
                    yield m.group("basefile"), link
                elif link == soughtnext:
                    nextpage = link
                    pagecount += 1
            if nextpage:
                url = nextpage
            else:
                done = True

    def download_single(self, basefile, url):
        assert url.endswith(".pdf"), "URL to download must be the PDF file"
        ret = super(JO, self).download_single(basefile, url)
        if ret or self.config.refresh:
            headnote_url = self.headnote_url_template % {'basefile': basefile}
            resp = requests.get(headnote_url)
            if "1 totalt antal träffar" in resp.text:
                # don't save the entire 100+ KB HTML mess when we only
                # want a litle 6 KB piece. Disk space is cheap but not
                # infinite
                soup = BeautifulSoup(resp.text, "lxml").find("div", "MidContent")
                soup.find("ol", "breadcrumb").decompose()
                soup.find("div", id="SearchSettings").decompose()
                with self.store.open_downloaded(basefile, mode="wb", attachment="headnote.html") as fp:
                    fp.write(soup.prettify().encode("utf-8"))
                self.log.debug("%s: downloaded headnote from %s" %
                               (basefile, headnote_url))
            else:
                self.log.warning("Could not find unique headnote for %s at %s" %
                                 (basefile, headnote_url))
        return ret

    def source_url(self, basefile):
        return ("http://www.jo.se/sv/JO-beslut/Soka-JO-beslut/"
                "?query=%(basefile)s&caseNumber=%(basefile)s" % locals())

    def extract_head(self, fp, basefile):
        if "headnote.html" in list(self.store.list_attachments(basefile,
                                                               "downloaded")):
            with self.store.open_downloaded(basefile,
                                            attachment="headnote.html") as fp:
                return BeautifulSoup(fp, "lxml")
        # else: return None

    def infer_identifier(self, basefile):
        return "JO dnr %s" % basefile.replace("/", "-")
        
    def extract_metadata(self, rawhead, basefile):
        d = self.metadata_from_basefile(basefile)
        if rawhead:  # sometimes there's no headnote.html
            for label, key in {"Ämbetsberättelse": 'dcterms:bibliographicCitation',
                               "Beslutsdatum": 'dcterms:issued',
                               "Diarienummer": 'rpubl:diarienummer'}.items():
                labelnode = rawhead.find(text=re.compile("%s:" % label))
                if labelnode:
                    d[key] = util.normalize_space(labelnode.next_sibling.text)
            # this data might contain spurious spaces due to <span
            # class="Definition"> tags -- see eg 3128-2002. Data in
            # the document is preferable
            d["dcterms:title"] = util.normalize_space(rawhead.find("h2").text)
        return d


    def polish_metadata(self, attribs, infer_nodes=True):
        resource = super(JO, self).polish_metadata(attribs, infer_nodes)
        # add a known foaf:name for the publisher to our polished graph
        # FIXME/NOTE: In swedishlegalsource.ttl, the foaf:name is
        # given as Riksdagens ombudsmän (and thus is used in TOC
        # generation). I think that "Justitieombudsmannen" is better.
        resource.value(DCTERMS.publisher).add(FOAF.name, Literal("Justitieombudsmannen", lang="sv"))
        return resource


    def postprocess_doc(self, doc):
        def helper(node, meta):
            for subnode in list(node):
                if isinstance(subnode, Meta):
                    kwargs = {'lang': getattr(subnode, 'lang', None),
                              'datatype': getattr(subnode, 'datatype', None)}
                    for s in subnode:
                        # A meta node for pred rpubl:diarienummer
                        # might have two str nodes -- we must not skip
                        # one
                        #
                        # if doc.meta.value(URIRef(doc.uri), subnode.predicate):
                        #     continue

                        # But if we find a dcterms:title, we throw the
                        # old one (probably gotten from the
                        # headnote.html) out, as it's probably lower
                        # quality
                        if subnode.predicate == DCTERMS.title:
                            oldtitle = doc.meta.value(URIRef(doc.uri), DCTERMS.title)
                            if oldtitle:
                                doc.meta.remove((URIRef(doc.uri), DCTERMS.title, oldtitle))
                        l = Literal(s, **kwargs)
                        meta.add((URIRef(doc.uri), subnode.predicate, l))
                    node.remove(subnode)
                elif isinstance(subnode, list):
                    helper(subnode, meta)
        helper(doc.body, doc.meta)
        d = doc.meta.value(URIRef(doc.uri), RPUBL.avgorandedatum)
        # only use the dcterms:issued value from the document if we
        # don't already have one from the metadata
        if d and not doc.meta.value(URIRef(doc.uri), DCTERMS.issued):
            doc.meta.add((URIRef(doc.uri), DCTERMS.issued, d))

    def tokenize(self, reader):
        def gluecondition(textbox, nextbox, prevbox):
            linespacing = nextbox.height / 1.5  # allow for large linespacing
            return (textbox.font.size == nextbox.font.size and
                    textbox.top + textbox.height + linespacing >= nextbox.top)
        return reader.textboxes(gluecondition)

    def get_parser(self, basefile, sanitized, parseconfig="default"):
        def is_heading(parser):
            return parser.reader.peek().font.size == 17

        def is_dnr(parser):
            chunk = parser.reader.peek()
            if (chunk.font.size == 12 and
                    re.match('\d+-\d{2,4}', str(chunk))):
                return True

        def is_datum(parser):
            chunk = parser.reader.peek()
            if (chunk.font.size == 12 and
                    re.match('\d{4}-\d{2}-\d{2}', str(chunk))):
                return True

        def is_nonessential(parser):
            chunk = parser.reader.peek()
            if chunk.top >= 1159 or chunk.top <= 146:
                return True

        def is_abstract(parser):
            if str(parser.reader.peek()).startswith("Beslutet i korthet:"):
                return True

        def is_section(parser):
            chunk = parser.reader.peek()
            strchunk = str(chunk)
            if chunk.font.size == 14 and chunk[0].tag == "b" and not strchunk.endswith("."):
                return True

        def is_blockquote(parser):
            chunk = parser.reader.peek()
            if chunk.left >= 255:
                return True

        def is_normal(parser):
            chunk = parser.reader.peek()
            if chunk.left < 255:
                return True

        def is_paragraph(parser):
            return True

        @decorators.newstate("body")
        def make_body(parser):
            return parser.make_children(Body())

        def make_heading(parser):
            # h = Heading(str(parser.reader.next()).strip())
            h = Meta([str(parser.reader.next()).strip()],
                     predicate=DCTERMS.title,
                     lang="sv")
            return h

        @decorators.newstate("abstract")
        def make_abstract(parser):
            a = Abstract([Paragraph(parser.reader.next())])
            return parser.make_children(a)

        @decorators.newstate("section")
        def make_section(parser):
            s = UnorderedSection(title=str(parser.reader.next()).strip())
            return parser.make_children(s)

        @decorators.newstate("blockquote")
        def make_blockquote(parser):
            b = Blockquote()
            return parser.make_children(b)

        def make_paragraph(parser):
            # A Paragraph containing PDFReader.Textelement object will
            # render these as <span> objects (the default rendering. A
            # PDFReader.Textbox object containing same will render
            # unstyled Textelements as plain strings, cutting down on
            # unneccesary <span> elements. However, these themselves
            # render with unneccessary @style and @class attributes,
            # which we don't want. For now, lets stick with Paragraphs
            # as containers and maybe later figure out how to get
            # PDFReader.Textelements to render themselves sanely.
            # 
            # p = parser.reader.next()
            p = Paragraph(parser.reader.next())
            return p

        def make_datum(parser):
            datestr = str(parser.reader.next()).strip()
            year = int(datestr.split("-")[0])
            if 2100 > year > 1970:
                parser.remove_recognizer(is_datum)
                d = [datestr]
                return Meta(d, predicate=RPUBL.avgorandedatum,
                            datatype=XSD.date)
            else:
                self.log.warning("Year in %s doesn't look valid" % datestr)
                return None

        def make_dnr(parser):
            parser.remove_recognizer(is_dnr)
            ds = [x for x in str(parser.reader.next()).strip().split(" ")]
            return Meta(ds, predicate=RPUBL.diarienummer)

        def skip_nonessential(parser):
            parser.reader.next()  # return nothing

        p = FSMParser()
        p.initial_state = "body"
        p.initial_constructor = make_body
        p.set_recognizers(is_datum,
                          is_dnr,
                          is_nonessential,
                          is_heading,
                          is_abstract,
                          is_section,
                          is_normal,
                          is_blockquote,
                          is_paragraph)
        p.set_transitions({("body", is_heading): (make_heading, None),
                           ("body", is_nonessential): (skip_nonessential, None),
                           ("body", is_datum): (make_datum, None),
                           ("body", is_dnr): (make_dnr, None),
                           ("body", is_abstract): (make_abstract, "abstract"),
                           ("body", is_section): (make_section, "section"),
                           ("body", is_blockquote): (make_blockquote, "blockquote"),
                           ("body", is_paragraph): (make_paragraph, None),
                           ("abstract", is_paragraph): (make_paragraph, None),
                           ("abstract", is_section): (False, None),
                           ("abstract", is_dnr): (False, None),
                           ("abstract", is_datum): (False, None),
                           ("section", is_paragraph): (make_paragraph, None),
                           ("section", is_nonessential): (skip_nonessential, None),
                           ("section", is_section): (False, None),
                           ("section", is_blockquote): (make_blockquote, "blockquote"),
                           ("section", is_datum): (make_datum, None),
                           ("section", is_dnr): (make_dnr, None),
                           ("blockquote", is_blockquote): (make_paragraph, None),
                           ("blockquote", is_nonessential): (skip_nonessential,  None),
                           ("blockquote", is_section): (False, None),
                           ("blockquote", is_normal): (False, None),
                           ("blockquote", is_datum): (make_datum, None),
                           ("blockquote", is_dnr): (make_dnr, None),
                           })
        p.debug = os.environ.get('FERENDA_FSMDEBUG', False)
        return p.parse

    _default_creator = "Riksdagens ombudsmän"

    def _relate_fulltext_value_rootlabel(self, desc):
        return desc.getvalue(DCTERMS.identifier)

    def tabs(self):
        if self.config.tabs:
            return [("JO", self.dataset_uri())]
        else:
            return []
