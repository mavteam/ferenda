# -*- coding: utf-8 -*-

# This fixture does a bunch of real HTTP request against a selected
# server (determined by the environment variable FERENDA_TESTURL,
# which is http://localhost:8000/ by default)
#
# When running against a local instance, it's important that this has
# been initialized with the documents in lagen/nu/res/scripts/testdata.txt

from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import *

# sys
import os
import unittest
import codecs
import re
from urllib.parse import urljoin
from datetime import datetime

# 3rdparty
import requests
from bs4 import BeautifulSoup
from rdflib import Graph, URIRef
from rdflib.namespace import DCTERMS

# own
from ferenda.elements import Link, serialize
from ferenda.testutil import FerendaTestCase
from ferenda.sources.legal.se import RPUBL
from lagen.nu import SFS, LNKeyword
from lagen.nu.wsgiapp import WSGIApp

class TestLagen(unittest.TestCase, FerendaTestCase):

    baseurl = os.environ.get("FERENDA_TESTURL", "http://localhost:8000/")

    def assert_status(self, url, code):
        res = requests.get(url, headers={'Accept': 'text/html'})
        self.assertEqual(res.status_code, code, url)
        return res
    
    def assert200(self, url):
        return self.assert_status(url, 200)

    def assert404(self, url):
        return self.assert_status(url, 404)

    def get(self, url, raise_for_status=False, **kwargs):
        if 'headers' not in kwargs:
            kwargs['headers']={'Accept': 'text/html'}
        res = requests.get(url, **kwargs)
        if raise_for_status:
            res.raise_for_status()
        return res
    

class TestPaths(TestLagen):

    def test_frontpage(self):
        self.assert200(self.baseurl)

    def test_nonexist(self):
        self.assert404(self.baseurl + "this-resource-does-not-exist")

    def test_specific_sfs(self):
        self.assert200(self.baseurl + "1999:175")

    def test_specific_dv(self):
        self.assert200(self.baseurl + "dom/nja/2015s180") # basefile HDO/Ö6229-14

    def test_specific_sou(self):
        self.assert200(self.baseurl + "sou/1997:39")
        # test old-style URI (for a while)
        self.assert200(self.baseurl + "utr/sou/1997:39")

    def test_specific_prop(self):
        self.assert200(self.baseurl + "prop/1997/98:44")

    def test_specific_keyword(self):
        self.assert200(self.baseurl + "begrepp/Personuppgift")
        
    def test_specific_keyword_tricky(self):
        self.assert200(self.baseurl + "begrepp/Sekundär_sekretessbestämmelse")

    def test_facsimile_page(self):
        res = self.get(self.baseurl + "sou/1997:39/sid557.png")
        self.assertEqual(200, res.status_code)
        self.assertEqual("image/png", res.headers["Content-Type"])
        # assert trough first 8 bytes (magic number) that this really
        # is a legit png
        import binascii
        self.assertEqual(b"89504e470d0a1a0a", binascii.hexlify(res.content[:8]))

        # assert that the old-style URI still works (for a time)
        res = self.get(self.baseurl + "utr/sou/1997:39/sid557.png")
        self.assertEqual(200, res.status_code)

    def test_feed_html(self):
        self.assert200(self.baseurl + "dataset/sitenews/feed")
        self.assert200(self.baseurl + "dataset/sfs/feed?rdf_type=type/forordning")

    def test_feed_atom(self):
        self.assert200(self.baseurl + "dataset/sitenews/feed.atom")
        self.assert200(self.baseurl + "dataset/sfs/feed.atom?rdf_type=type/forordning")

    def test_attached_css(self):
        res = self.get(self.baseurl + "bolfs/2008:1")
        self.assertEqual(200, res.status_code)
        self.assertEqual("text/html; charset=utf-8", res.headers["Content-Type"])
        self.assertIn('<link rel="stylesheet" href="/bolfs/2008:1?dir=parsed&amp;attachment=index.css"/>', res.text[:1200])
        res = self.get(self.baseurl + "bolfs/2008:1?dir=parsed&attachment=index.css")
        self.assertEqual(200, res.status_code)
        self.assertEqual("text/css", res.headers["Content-Type"])

class TestPages(TestLagen):
    def test_doctype(self):
        for doc in ("", "1999:175", "dom/nja/2015s180", "sou/1997:39", "prop/1997/98:44",
                    "begrepp/Personuppgift", "begrepp/Sekundär_sekretessbestämmelse"):
            resp = self.get(self.baseurl + doc)
            self.assertEqual('<!DOCTYPE html SYSTEM "about:legacy-compat">',
                             resp.text[:44], "Wrong doctype for %s" % doc)


    def test_frontpage_links(self):
        # <a> elements should have a href attribute (you'd think that
        # was obvious, but it's not)
        res = self.get(self.baseurl)
        soup = BeautifulSoup(res.text, "lxml")
        firstlink = soup.article.a
        self.assertTrue(firstlink.get("href"))

    def test_frontpage_disabled_links(self):
        res = self.get(self.baseurl)
        soup = BeautifulSoup(res.text, "lxml")
        local = not os.environ.get("FERENDA_TESTURL")
        if local:
            # don't test for broken links in the main content area
            # since there will be many (in local testing we only
            # download a small subset of laws and other resources, and
            # the main content area contains links to other
            # resources. Thus, in this testing scenario, they're
            # expected to be missing
            soup.find("div", "section-wrapper").decompose()
        for link in soup.find_all("a"):
            self.assertNotIn("invalid-link", link.attrs.get('class', []), "Link %s marked as invalid (not in DB)" % link.text)

    def test_css_link(self):
        for link in ("", "dom/nja/2015s180", "dom/hfd/2015/not/1"):
            url = self.baseurl + link
            res = self.get(url)
            soup = BeautifulSoup(res.text, "lxml")
            cssref = soup.find("link", rel="stylesheet", href=re.compile("ferenda.css$"))['href']
            cssurl = urljoin(url, cssref)
            self.assertEqual(self.baseurl + "rsrc/css/ferenda.css",
                             cssurl, "Error for %s" % url)

    def test_sfs_outline(self):
        res = self.get(self.baseurl + "1999:175")
        soup = BeautifulSoup(res.text, "lxml")
        outlines = soup.find("nav", id="toc").find_all("li")
        # make sure the outline navigation is as expected and hasn't
        # been mangled.
        self.assertIn('Ett offentligt rättsinformationssystem', outlines[0].a.text)
        subheadings = outlines[1].find_all("li")
        self.assertEqual(9, len(subheadings))
        self.assertIn('Personuppgifter', subheadings[-1].a.text)

    def test_paragrafbeteckning(self):
        for doc in ("1949:105", "1999:175"):
            res = self.get(self.baseurl + doc)
            soup = BeautifulSoup(res.text, "lxml")
            self.assertTrue(soup.find("a", "paragrafbeteckning"),
                            "%s lacks marked-up paragrafbeteckning" % doc)

            
class TestPatching(TestLagen):

    def test_file_has_been_patched(self):
        # the encoding parameter might be a py3-ism
        needle = codecs.encode("Fjrebgrp", encoding="rot13")# rot13 of a sensitive name
        res = self.get(self.baseurl + "dom/nja/2002s35")    # case containing sensitive info
        res.raise_for_status()                              # req succeded
        self.assertEqual(-1, res.text.find(needle))         # sensitive name is removed
        self.assertTrue(res.text.index("alert alert-warning patchdescription")) # patching is advertised

class TestConNeg(TestLagen):
    # this basically mirrors testWSGI.ConNeg
    def test_basic(self):
        res = self.get(self.baseurl + "1999:175")
        self.assertEqual(200, res.status_code)
        self.assertEqual("text/html; charset=utf-8", res.headers['Content-Type'])

    def test_xhtml(self):
        res = self.get(self.baseurl + "1999:175",
                       headers={'Accept': 'application/xhtml+xml'})
        self.assertEqual(200, res.status_code)
        self.assertEqual("application/xhtml+xml", res.headers['Content-Type'])
        # variation: use file extension
        res = self.get(self.baseurl + "1999:175.xhtml")
        self.assertEqual(200, res.status_code)
        self.assertEqual("application/xhtml+xml", res.headers['Content-Type'])

    def test_rdf(self):
        # basic test 3: accept: application/rdf+xml -> RDF statements (in XML)
        res = self.get(self.baseurl + "1999:175",
                       headers={'Accept': 'application/rdf+xml'})
        self.assertEqual(200, res.status_code)
        self.assertEqual("application/rdf+xml", res.headers['Content-Type'])
        # variation: use file extension
        res = self.get(self.baseurl + "1999:175.rdf")
        self.assertEqual(200, res.status_code)
        self.assertEqual("application/rdf+xml", res.headers['Content-Type'])

    def test_ntriples(self):
        # transform test 4: accept: application/n-triples -> RDF statements (in NTriples)

        # get the untransformed data to compare with
        g = Graph().parse(data=self.get(self.baseurl + "1999:175.rdf", raise_for_status=True).text)
        res = self.get(self.baseurl + "1999:175",
                       headers={'Accept': 'application/n-triples'})
        self.assertEqual(200, res.status_code)
        self.assertEqual("application/n-triples", res.headers['Content-Type'])
        got = Graph().parse(data=res.content, format="nt")
        self.assertEqualGraphs(g, got)

        # variation: use file extension
        res = self.get(self.baseurl + "1999:175.nt", raise_for_status=True)
        self.assertEqual(200, res.status_code)
        self.assertEqual("application/n-triples", res.headers['Content-Type'])
        got = Graph()
        got.parse(data=res.content, format="nt")
        self.assertEqualGraphs(g, got)

    def test_turtle(self):
        # transform test 5: accept: text/turtle -> RDF statements (in Turtle)
        g = Graph().parse(data=self.get(self.baseurl + "1999:175.rdf", raise_for_status=True).text)
        res = self.get(self.baseurl + "1999:175",
                       headers={'Accept': 'text/turtle'})
        self.assertEqual(200, res.status_code)
        self.assertEqual("text/turtle", res.headers['Content-Type'])
        got = Graph().parse(data=res.content, format="turtle")
        self.assertEqualGraphs(g, got)

        # variation: use file extension
        res = self.get(self.baseurl + "1999:175.ttl")
        self.assertEqual(200, res.status_code)
        self.assertEqual("text/turtle", res.headers['Content-Type'])
        got = Graph()
        got.parse(data=res.content, format="turtle")
        self.assertEqualGraphs(g, got)

    def test_json(self):
        # transform test 6: accept: application/json -> RDF statements (in JSON-LD)
        g = Graph().parse(data=self.get(self.baseurl + "1999:175.rdf").text)
        res = self.get(self.baseurl + "1999:175",
                       headers={'Accept': 'application/json'})
        self.assertEqual(200, res.status_code)
        self.assertEqual("application/json", res.headers['Content-Type'])
        got = Graph().parse(data=res.text, format="json-ld")
        self.assertEqualGraphs(g, got)

        # variation: use file extension
        res = self.get(self.baseurl + "1999:175.json")
        self.assertEqual(200, res.status_code)
        self.assertEqual("application/json", res.headers['Content-Type'])
        got = Graph()
        got.parse(data=res.text, format="json-ld")
        self.assertEqualGraphs(g, got)

    def test_unacceptable(self):
        res = self.get(self.baseurl + "1999:175",
                       headers={'Accept': 'application/pdf'})
        self.assertEqual(res.status_code, 406)
        self.assertEqual("text/html; charset=utf-8", res.headers['Content-Type'])

        # variation: unknown file extension should also be unacceptable
        res = self.get(self.baseurl + "1999:175.pdf")
        self.assertEqual(res.status_code, 406)
        self.assertEqual("text/html; charset=utf-8", res.headers['Content-Type'])

    def test_extended_rdf(self):
        # extended test 6: accept: "/data" -> extended RDF statements
        g = Graph().parse(data=self.get(self.baseurl + "1999:175/data.rdf").text)
        
        res = self.get(self.baseurl + "1999:175/data",
                       headers={'Accept': 'application/rdf+xml'})
        self.assertEqual(200, res.status_code)
        self.assertEqual("application/rdf+xml", res.headers['Content-Type'])
        got = Graph().parse(data=res.text)
        self.assertEqualGraphs(g, got)

    def test_extended_ntriples(self):
        # extended test 7: accept: "/data" + "application/n-triples" -> extended
        # RDF statements in NTriples
        g = Graph().parse(data=self.get(self.baseurl + "1999:175/data.rdf").text)
        res = self.get(self.baseurl + "1999:175/data",
                     headers={'Accept': 'application/n-triples'})
        self.assertEqual(200, res.status_code)
        self.assertEqual("application/n-triples", res.headers['Content-Type'])
        got = Graph().parse(data=res.text, format="nt")
        self.assertEqualGraphs(g, got)
        # variation: use file extension
        res = self.get(self.baseurl + "1999:175/data.nt")
        self.assertEqual(200, res.status_code)
        self.assertEqual("application/n-triples", res.headers['Content-Type'])
        got = Graph().parse(data=res.text, format="nt")
        self.assertEqualGraphs(g, got)

    def test_extended_turtle(self):
        # extended test 7: accept: "/data" + "text/turtle" -> extended
        # RDF statements in Turtle
        g = Graph().parse(data=self.get(self.baseurl + "1999:175/data.rdf").text)
        res = self.get(self.baseurl + "1999:175/data",
                     headers={'Accept': 'text/turtle'})
        self.assertEqual(200, res.status_code)
        self.assertEqual("text/turtle", res.headers['Content-Type'])
        got = Graph().parse(data=res.content, format="turtle")
        self.assertEqualGraphs(g, got)
        # variation: use file extension
        res = self.get(self.baseurl + "1999:175/data.ttl")
        self.assertEqual(200, res.status_code)
        self.assertEqual("text/turtle", res.headers['Content-Type'])
        got = Graph().parse(data=res.content, format="turtle")
        self.assertEqualGraphs(g, got)

    def test_dataset_html(self):
        res = self.get(self.baseurl  + "dataset/sfs")
        self.assertTrue(res.status_code, 200)
        self.assertEqual("text/html; charset=utf-8", res.headers['Content-Type'])

    def test_dataset_html_param(self):
        res = self.get(self.baseurl  + "dataset/sfs?titel=P")
        self.assertTrue(res.status_code, 200)
        self.assertEqual("text/html; charset=utf-8", res.headers['Content-Type'])
        self.assertIn('Författningar som börjar på "P"', res.text)

    def test_dataset_ntriples(self):
        res = self.get(self.baseurl  + "dataset/sitenews",
                       headers={'Accept': 'application/n-triples'})
        self.assertTrue(res.status_code, 200)
        self.assertEqual("application/n-triples", res.headers['Content-Type'])
        Graph().parse(data=res.text, format="nt")
        res = self.get(self.baseurl  + "dataset/sitenews.nt")
        self.assertTrue(res.status_code, 200)
        self.assertEqual("application/n-triples", res.headers['Content-Type'])
        Graph().parse(data=res.text, format="nt")

    def test_dataset_turtle(self):
        res = self.get(self.baseurl  + "dataset/sitenews",
                       headers={'Accept': 'text/turtle'})
        self.assertTrue(res.status_code, 200)
        self.assertEqual("text/turtle", res.headers['Content-Type'])
        Graph().parse(data=res.text, format="turtle")
        res = self.get(self.baseurl  + "dataset/sitenews.ttl")
        self.assertTrue(res.status_code, 200)
        self.assertEqual("text/turtle", res.headers['Content-Type'])
        Graph().parse(data=res.text, format="turtle")

    def test_dataset_xml(self):
        res = self.get(self.baseurl  + "dataset/sitenews",
                       headers={'Accept': 'application/rdf+xml'})
        self.assertTrue(res.status_code, 200)
        self.assertEqual("application/rdf+xml", res.headers['Content-Type'])
        Graph().parse(data=res.text)
        res = self.get(self.baseurl  + "dataset/sitenews.rdf")
        self.assertTrue(res.status_code, 200)
        self.assertEqual("application/rdf+xml", res.headers['Content-Type'])
        Graph().parse(data=res.text)


    def test_facsimile_page_ie_accept(self):
        # IE uses this accept header, which triggered a 406 error from wsgiapp
        # res = self.get(self.baseurl + "utr/sou/1997:39/sid557.png",
        res = self.get(self.baseurl + "dir/2016:15/sid1.png",
                       headers={'Accept': "text/html, application/xhtml+xml, image/jxr, */*"})
        self.assertEqual(200, res.status_code)
        self.assertEqual("image/png", res.headers["Content-Type"])
        # assert trough first 8 bytes (magic number) that this really
        # is a legit png
        import binascii
        self.assertEqual(b"89504e470d0a1a0a", binascii.hexlify(res.content[:8]))


class TestAnnotations(TestLagen):

    def test_inbound_links(self):
        res = self.get(self.baseurl + "1949:105/data", True,
                       headers={'Accept': 'application/rdf+xml'})
        graph = Graph().parse(data=res.text, format="xml")
        resource = graph.resource(URIRef("https://lagen.nu/1949:105"))
        self.assertEqual(str(resource.value(DCTERMS.title)), "Tryckfrihetsförordning (1949:105)")
        # Assert a few things about inbound relations
        resource = graph.resource(URIRef("https://lagen.nu/1949:105#K3P3"))

        # see if an expected legal case + inbound statute reference is
        # as expected
        resource2 = next(x for x in resource.objects(RPUBL.isLagrumFor) if x._identifier == URIRef("https://lagen.nu/dom/nja/2015s166"))
        self.assertEqual("NJA 2015 s. 166",
                         str(resource2.value(DCTERMS.identifier)))
        resource2 = next(x for x in resource.objects(DCTERMS.isReferencedBy) if x._identifier == URIRef("https://lagen.nu/1991:1469#K10P1S5"))
        self.assertEqual("10 kap. 1 § 5 st Yttrandefrihetsgrundlag (1991:1469)",
                         str(resource2.value(DCTERMS.identifier)))
        self.assertIn("Anonymiteten skyddas genom att",
                      resource.value(DCTERMS.description))
        
    def test_wiki_comments(self):
        res = self.get(self.baseurl + "1949:105")
        # make sure the wiki commentary is weaved in. NOTE: if the
        # wiki commentary changes, this test has to be updated.
        self.assertIn("Hemsidor, bloggar och innehållet i andra databaser", res.text)

    def test_wiki_concept(self):
        res = self.get(self.baseurl + "begrepp/Sekundär_sekretessbestämmelse")
        self.assertNotIn("Beskrivning saknas!", res.text)
        
class TestSearch(TestLagen):

    def totalhits(self, soup):
        return int(soup.find("h1").text.split()[0])
        
    def test_basic_search(self):
        # assert that left nav contains a number of results with at least x hits
        res = self.get(self.baseurl + "search/?q=personuppgift", raise_for_status=True)
        soup = BeautifulSoup(res.text, "lxml")
        self.assertGreaterEqual(self.totalhits(soup), 14)
        nav = soup.find("nav", id="toc")
        for repo, minhits in (("dv", 3),
                              ("prop", 3),
                              ("myndfs", 2),
                              ("sou", 2),
                              ("ds", 1),
                              ("mediawiki", 1),
                              ("sfs", 1),
                              ("static", 1)):
            link = nav.find("a", href=re.compile("type=%s" % repo))
            self.assertIsNotNone(link, "Found no nav link of type=%s" % repo)
            hits = int(link.parent.span.text) # a <span class="badge pull-right">42</span>
            self.assertGreaterEqual(hits, minhits, "Expected more hits for %s" % repo)

    def test_faceted_search(self):
        res = self.get(self.baseurl + "search/?q=personuppgift", raise_for_status=True)
        totalhits = self.totalhits(BeautifulSoup(res.text, "lxml"))
        soup = BeautifulSoup(self.get(self.baseurl + "search/?q=personuppgift&type=dv").text,
                             "lxml")
        self.assertLess(self.totalhits(soup), totalhits)
        # for some reason, this search keyword yields ghost hits when using faceting
        totalhits = self.totalhits(BeautifulSoup(self.get(
            self.baseurl + "search/?q=avtal").text, "lxml"))
        soup = BeautifulSoup(self.get(self.baseurl + "search/?q=avtal&type=dv").text,
                             "lxml")
        self.assertLess(self.totalhits(soup), totalhits)

        # go on and test that the facets in the navbar is as they should

    def test_sfs_title(self):
        soup = BeautifulSoup(self.get(self.baseurl + "search/?q=personuppgiftslag").text,
                             "lxml")
        # examine if the first hit is the SFS with that exact title
        # (well, actually a title that starts with the exact same
        # string). NB: The SFS should rank above prop 1997/98:44 which
        # has the exact same title. We do this by boosting the sfs
        # index.
        hits = soup.find_all("section", "hit")
        hit = hits[0]
        self.assertEqual(hit.b.a.get("href"), "/1998:204")
        for hit in hits:
            self.assertNotRegex(hit.b.a.text, "SFS \d+:\d+", "placeholder title used instead of real SFS title")

    def test_stemming(self):
        # "bulvanutredning" never occurs in the plain text, but
        # "bulvanutredningen" does. Check if proper stemming has been
        # applied when indexing
        soup = BeautifulSoup(self.get(self.baseurl + "search/?q=bulvanutredning").text,
                             "lxml")
        hit = soup.find("section", "hit")
        self.assertTrue(hit)

        # also, check that the query itself is properly stemmed. It'd
        # be weird if "bulvanutredningen" yielded no hits as the exact
        # word occurs in the text.
        soup = BeautifulSoup(self.get(self.baseurl + "search/?q=bulvanutredningen").text,
                             "lxml")
        hit = soup.find("section", "hit")
        self.assertTrue(hit)
        
    def test_scoring(self):
        # really a regression test -- this query should never match anything other than prop/sou/ds/dir
        soup = BeautifulSoup(self.get(self.baseurl + "search/?q=bulvanutredningen").text,
                             "lxml")
        hits = soup.find_all("section", "hit")
        self.assertTrue(hits)
        for hit in hits:
            self.assertTrue(hit.b.a.get("href").startswith(("/prop/", "/dir/", "/sou/", "/ds/")),
                            "%s isn't prop/dir/sou/ds" % hit.b.a.get("href"))
        
    def test_innerhits(self):
        soup = BeautifulSoup(self.get(self.baseurl + "search/?q=personuppgiftsbiträde&type=sou&issued=2016").text, "lxml") # should match SOU 2016:41
        firsthit = soup.find_all("section", "hit")[0]
        # assert that the hit has no content apart FROM innerhits
        maintext = "".join([x.get_text().strip() for x in firsthit.find_all("p", class_=False)])
        self.assertEqual("", maintext)
        innerhits = soup.find_all("p", "innerhit")
        self.assertTrue(len(innerhits))
        for innerhit in innerhits:
            link = innerhit.a.get("href")
            self.assertTrue("#S" in link or "#B" in link or "#kommentar" in link,  "link %s doesn't look section-y" % link)
            self.assertNotIn("(beteckning saknas)", innerhit.a.text)
        

class TestAutocomplete(TestLagen):
    def test_basic_sfs(self):
        res = self.get(self.baseurl + "api/?q=3+§+förvaltningslag&_ac=true",
                       headers={'Accept': 'application/json'})
        # returns eg [{'url': 'http://localhost:8000/2017:900#P3',
        #              'label': '3 §',
        #              'comment': '3 § förvaltningslagen',
        #              'desc': 'U brottsbekämpande verksamhet hos...'}]
        self.assertEqual('application/json', res.headers['Content-Type'])
        hits = res.json()
        self.assertEqual(hits[0]['url'], self.baseurl + "2017:900#P3")
        self.assertTrue(hits[0]['desc'].startswith("I denna lag"))
        self.assertGreaterEqual(len(hits), 1) # "3 §
                                              # förvaltningslagen"
                                              # should only match one
                                              # thing
                                              # ("förvaltningslagen
                                              # 3" matches several)

    def test_shortform_sfs(self):
        res = self.get(self.baseurl + "api/?q=TF+2:&_ac=true",
                       headers={'Accept': 'application/json'})
        hits = res.json()
        # for idx, h in enumerate(hits):
        #     print(idx+1, h['url'])
        # We assume that the first section retrieved will be section 1
        # ("2 kap 1 §"). This requires that the search returns hits in
        # the same order that they were indexed in, which might not
        # always be guaranteed.
        self.assertEqual(hits[0]['url'], self.baseurl + "1949:105#K2P1")
        self.assertEqual(hits[0]['label'], "2 kap. 1 § Tryckfrihetsförordning (1949:105)")
        self.assertTrue(hits[0]['desc'].startswith("Till främjande av ett fritt meningsutbyte"))

    def test_incomplete_lawname(self):
        res = self.get(self.baseurl + "api/?q=personuppgiftsl&_ac=true",
                       headers={'Accept': 'application/json'})
        hits = res.json()
        self.assertEqual(hits[0]['url'], self.baseurl + "1998:204")
        self.assertEqual(hits[0]['label'], "Personuppgiftslag (1998:204)")

        res = self.get(self.baseurl + "api/?q=TRYCK&_ac=true", # check that case insensitivity works
                       headers={'Accept': 'application/json'})
        hits = res.json()
        self.assertEqual(hits[0]['url'], self.baseurl + "1949:105")
        self.assertEqual(hits[0]['label'], "Tryckfrihetsförordning (1949:105)")

    def test_basic_dv(self):
        res = self.get(self.baseurl + "api/?q=NJA+2015+s+16&_ac=true",
                       headers={'Accept': 'application/json'})
        hits = res.json()
        wantedhit = None
        for hit in hits:
            if hit['url'] == self.baseurl + "dom/nja/2015s166":
                wantedhit = hit
        self.assertTrue(wantedhit)
        self.assertEqual(wantedhit['label'], "NJA 2015 s. 166")
        self.assertEqual(wantedhit['desc'], "Brott mot tystnadsplikten enligt tryckfrihetsförordningen.")
        
    def test_basic_prop(self):
        res = self.get(self.baseurl + "api/?q=prop+1997/98:4&_ac=true",
                       headers={'Accept': 'application/json'})
        hits = res.json()
        wantedhit = None
        self.assertLessEqual(len(hits), 10) # return at most 10 hits
        for hit in hits:
            if hit['url'] == self.baseurl + "prop/1997/98:44":
                wantedhit = hit
            # for this kind of query, only documents, not doc
            # fragments (pages) should be returned
            self.assertFalse("#sid" in hit['url'], "%s is page fragment not doc" % hit['url'])
        # make sure the doc we want is among the 10 
        self.assertTrue(wantedhit)
        self.assertEqual(wantedhit['label'], "Prop. 1997/98:44")
        self.assertEqual(wantedhit['desc'], "Personuppgiftslag")

# this is a local test, don't need to run it if we're running the test
# suite against a remote server
@unittest.skipIf(os.environ.get("FERENDA_TESTURL"), "Not testing against local dev server")
class TestACExpand(unittest.TestCase):

    def setUp(self):
        self.wsgiapp = WSGIApp(repos=[SFS(datadir="tng.lagen.nu/data")])

    def test_expand_shortname(self):
        self.assertEqual("https://lagen.nu/1949:105#K",
                         self.wsgiapp.expand_partial_ref("TF"))

    def test_expand_chapters(self):
        self.assertEqual("https://lagen.nu/1949:105#K1",
                         self.wsgiapp.expand_partial_ref("TF 1"))

    def test_expand_all_sections(self):
        self.assertEqual("https://lagen.nu/1949:105#K1P",
                         self.wsgiapp.expand_partial_ref("TF 1:"))

    def test_expand_prefixed_sections(self):
        self.assertEqual("https://lagen.nu/1949:105#K1P1",
                         self.wsgiapp.expand_partial_ref("TF 1:1"))

    def test_chapterless_expand_all_sections(self):
        self.assertTrue(os.path.exists("tng.lagen.nu/data/sfs/distilled/1998/204.rdf"))
        self.assertEqual("https://lagen.nu/1998:204#P",
                         self.wsgiapp.expand_partial_ref("PUL"))

    def test_chapterless_expand_prefixed_sections(self):
        self.assertTrue(os.path.exists("tng.lagen.nu/data/sfs/distilled/1998/204.rdf"))
        self.assertEqual("https://lagen.nu/1998:204#P3",
                         self.wsgiapp.expand_partial_ref("PUL 3"))

    def test_prop_start(self):
        self.assertEqual("https://lagen.nu/prop/",
                         self.wsgiapp.expand_partial_ref("prop"))

    def test_prop_incomplete_year(self):
        self.assertEqual("https://lagen.nu/prop/199",
                         self.wsgiapp.expand_partial_ref("prop 199"))

    def test_prop_year(self):
        self.assertEqual("https://lagen.nu/prop/1997",
                         self.wsgiapp.expand_partial_ref("prop 1997"))

    def test_prop_missing_num(self):
        self.assertEqual("https://lagen.nu/prop/1997/98:",
                         self.wsgiapp.expand_partial_ref("prop 1997/98:"))

    def test_prop_complete(self):
        self.assertEqual("https://lagen.nu/prop/1997/98:44",
                         self.wsgiapp.expand_partial_ref("prop 1997/98:44"))

    def test_prop_missing_page(self):
        self.assertEqual("https://lagen.nu/prop/1997/98:44#sid",
                         self.wsgiapp.expand_partial_ref("prop 1997/98:44 s"))

    def test_prop_complete(self):
        self.assertEqual("https://lagen.nu/prop/1997/98:44#sid12",
                         self.wsgiapp.expand_partial_ref("prop 1997/98:44 s. 12"))


@unittest.skipIf(":8000" in os.environ.get("FERENDA_TESTURL", "http://localhost:8000"), "Not testing against dev server")
class TestNginxServing(TestLagen):

    def assertNginx(self, url):
        res = self.get(url)
        self.assertIsNone(res.headers.get("X-WSGI-app"), "%s wasn't served by nginx directly" % url)

    def assertWsgi(self, url):
        res = self.get(url)
        self.assertEqual("ferenda", res.headers.get("X-WSGI-app"), "%s wasn't served by the WSGI app" % url)

    def test_frontpage(self):
        self.assertNginx(self.baseurl)

    def test_doc(self):
        self.assertNginx(self.baseurl + "dom/nja/2015s180")

    def test_toc(self):
        self.assertNginx(self.baseurl + "dataset/dv")

    def test_search(self):
        self.assertWsgi(self.baseurl + "search/?q=personuppgift")
    

class TestKeywordToc(unittest.TestCase):
    maxDiff = None
    def makeitem(self, text):
        return [Link(text, uri="https://lagen.nu/begrepp/" + text.replace("»", "//").replace(" ", "_"))]

    def do_test(self, keywords, want):
        repo = LNKeyword()
        body = repo.toc_generate_page_body(map(self.makeitem, keywords), None)
        got = serialize(body[1])
        self.assertEqual(want, got)
        
        
    def test_prefix_segmentation(self):
        self.do_test(["Abc",
                      "Abd",
                      "Abe",
                      "Afg",
                      "Ahi",
                      "Ahj",
                      "Ahk"],
                      """<Div class="threecol">
  <H2>
    <str>Ab</str>
  </H2>
  <UnorderedList>
    <ListItem>
      <Link uri="https://lagen.nu/begrepp/Abc">Abc</Link>
    </ListItem><ListItem>
      <Link uri="https://lagen.nu/begrepp/Abd">Abd</Link>
    </ListItem><ListItem>
      <Link uri="https://lagen.nu/begrepp/Abe">Abe</Link>
    </ListItem>
  </UnorderedList>
  <H2>
    <str>Af</str>
  </H2>
  <UnorderedList>
    <ListItem>
      <Link uri="https://lagen.nu/begrepp/Afg">Afg</Link>
    </ListItem>
  </UnorderedList>
  <H2>
    <str>Ah</str>
  </H2>
  <UnorderedList>
    <ListItem>
      <Link uri="https://lagen.nu/begrepp/Ahi">Ahi</Link>
    </ListItem><ListItem>
      <Link uri="https://lagen.nu/begrepp/Ahj">Ahj</Link>
    </ListItem><ListItem>
      <Link uri="https://lagen.nu/begrepp/Ahk">Ahk</Link>
    </ListItem>
  </UnorderedList>
</Div>
""")
        

    def test_segmentation_casing(self):
        self.do_test(["Albanien",
                      "ALFA",
                      "Algolean"], """<Div class="threecol">
  <H2>
    <str>Al</str>
  </H2>
  <UnorderedList>
    <ListItem>
      <Link uri="https://lagen.nu/begrepp/Albanien">Albanien</Link>
    </ListItem><ListItem>
      <Link uri="https://lagen.nu/begrepp/ALFA">ALFA</Link>
    </ListItem><ListItem>
      <Link uri="https://lagen.nu/begrepp/Algolean">Algolean</Link>
    </ListItem>
  </UnorderedList>
</Div>
""")
    
    def test_nested(self):
        self.do_test(["Abc",
                      "Abc»D",
                      "Abc»D»Efg",
                      "Abc»D»Hij",
                      # Note that there is no "Abc»K" entry -- the test should create a non-linked "phantom" entry
                      "Abc»K»Lmn",
                      "Abc»K»Opq",
                      "Ars"],
                     """<Div class="threecol">
  <H2>
    <str>Ab</str>
  </H2>
  <UnorderedList>
    <ListItem>
      <Link uri="https://lagen.nu/begrepp/Abc">Abc</Link>
      <UnorderedList>
        <ListItem>
          <Link uri="https://lagen.nu/begrepp/Abc//D">D</Link>
          <UnorderedList>
            <ListItem>
              <Link uri="https://lagen.nu/begrepp/Abc//D//Efg">Efg</Link>
            </ListItem><ListItem>
              <Link uri="https://lagen.nu/begrepp/Abc//D//Hij">Hij</Link>
            </ListItem>
          </UnorderedList>
        </ListItem><ListItem>
          <str>K</str>
          <UnorderedList>
            <ListItem>
              <Link uri="https://lagen.nu/begrepp/Abc//K//Lmn">Lmn</Link>
            </ListItem><ListItem>
              <Link uri="https://lagen.nu/begrepp/Abc//K//Opq">Opq</Link>
            </ListItem>
          </UnorderedList>
        </ListItem>
      </UnorderedList>
    </ListItem>
  </UnorderedList>
  <H2>
    <str>Ar</str>
  </H2>
  <UnorderedList>
    <ListItem>
      <Link uri="https://lagen.nu/begrepp/Ars">Ars</Link>
    </ListItem>
  </UnorderedList>
</Div>
""")

    def test_nested_mixed(self):
        self.do_test(["Abc",
                      "Abc»D",
                      "Abf",
                      "Abf»G"],
                      """<Div class="threecol">
  <H2>
    <str>Ab</str>
  </H2>
  <UnorderedList>
    <ListItem>
      <Link uri="https://lagen.nu/begrepp/Abc">Abc</Link>
      <UnorderedList>
        <ListItem>
          <Link uri="https://lagen.nu/begrepp/Abc//D">D</Link>
        </ListItem>
      </UnorderedList>
    </ListItem><ListItem>
      <Link uri="https://lagen.nu/begrepp/Abf">Abf</Link>
      <UnorderedList>
        <ListItem>
          <Link uri="https://lagen.nu/begrepp/Abf//G">G</Link>
        </ListItem>
      </UnorderedList>
    </ListItem>
  </UnorderedList>
</Div>
""")


    def test_phantoms(self):
        self.do_test(["Alkoholdryck»Sprit",
                      "Allmän försäkring»Sjukpenninggrundande inkomst"],
                     """<Div class="threecol">
  <H2>
    <str>Al</str>
  </H2>
  <UnorderedList>
    <ListItem>
      <str>Alkoholdryck</str>
      <UnorderedList>
        <ListItem>
          <Link uri="https://lagen.nu/begrepp/Alkoholdryck//Sprit">Sprit</Link>
        </ListItem>
      </UnorderedList>
    </ListItem><ListItem>
      <str>Allmän försäkring</str>
      <UnorderedList>
        <ListItem>
          <Link uri="https://lagen.nu/begrepp/Allmän_försäkring//Sjukpenninggrundande_inkomst">Sjukpenninggrundande inkomst</Link>
        </ListItem>
      </UnorderedList>
    </ListItem>
  </UnorderedList>
</Div>
""")
        
    def test_threelevels_phantom(self):
        self.do_test(["Analysmetod",
                      "Analys»Principalkomponentanalys»Sensorisk analys"],
                     """<Div class="threecol">
  <H2>
    <str>An</str>
  </H2>
  <UnorderedList>
    <ListItem>
      <Link uri="https://lagen.nu/begrepp/Analysmetod">Analysmetod</Link>
    </ListItem><ListItem>
      <str>Analys</str>
      <UnorderedList>
        <ListItem>
          <str>Principalkomponentanalys</str>
          <UnorderedList>
            <ListItem>
              <Link uri="https://lagen.nu/begrepp/Analys//Principalkomponentanalys//Sensorisk_analys">Sensorisk analys</Link>
            </ListItem>
          </UnorderedList>
        </ListItem>
      </UnorderedList>
    </ListItem>
  </UnorderedList>
</Div>
""")


    def test_nested_wat(self):
        # Some corner cases that broke the previous version of
        # toc_generate_page_body_thread
        self.do_test(['Allmän försäkring»Sjukpenninggrundande inkomst',
                      'Allmän försäkring vårdbidrag',
                      'Allmän försäkring»Återbetalning av sjukpenning'],
                     """<Div class="threecol">
  <H2>
    <str>Al</str>
  </H2>
  <UnorderedList>
    <ListItem>
      <str>Allmän försäkring</str>
      <UnorderedList>
        <ListItem>
          <Link uri="https://lagen.nu/begrepp/Allmän_försäkring//Sjukpenninggrundande_inkomst">Sjukpenninggrundande inkomst</Link>
        </ListItem>
      </UnorderedList>
    </ListItem><ListItem>
      <Link uri="https://lagen.nu/begrepp/Allmän_försäkring_vårdbidrag">Allmän försäkring vårdbidrag</Link>
    </ListItem><ListItem>
      <str>Allmän försäkring</str>
      <UnorderedList>
        <ListItem>
          <Link uri="https://lagen.nu/begrepp/Allmän_försäkring//Återbetalning_av_sjukpenning">Återbetalning av sjukpenning</Link>
        </ListItem>
      </UnorderedList>
    </ListItem>
  </UnorderedList>
</Div>
""")

        self.do_test(['Allmän försäkring vårdbidrag',
                      'Allmän försäkring»Återbetalning av sjukpenning'],
                     """<Div class="threecol">
  <H2>
    <str>Al</str>
  </H2>
  <UnorderedList>
    <ListItem>
      <Link uri="https://lagen.nu/begrepp/Allmän_försäkring_vårdbidrag">Allmän försäkring vårdbidrag</Link>
    </ListItem><ListItem>
      <str>Allmän försäkring</str>
      <UnorderedList>
        <ListItem>
          <Link uri="https://lagen.nu/begrepp/Allmän_försäkring//Återbetalning_av_sjukpenning">Återbetalning av sjukpenning</Link>
        </ListItem>
      </UnorderedList>
    </ListItem>
  </UnorderedList>
</Div>
""")


class MetadataOnly(TestLagen):

    # a document marked as "metadataonly" in options.py should return
    # a 404 when requested, but the response should still be a custom
    # page (saved to disk as eg sou/generated/2008/5.html.404) with
    # proper title, links to source, explanation etc
    def test_404_status(self):
        res = self.get(self.baseurl + "sou/2008:5")
        self.assertEqual(res.status_code, 404)
        # should have a proper header
        self.assertIn("Könsdiskriminerande reklam", res.text)
        # should have an explaination
        self.assertIn("<h2>Dokumenttext saknas</h2>", res.text)
        # should have links to source
        self.assertIn('<a href="https://www.regeringen.se/rattsliga-dokument/statens-offentliga-utredningar/2008/01/sou-20085/">Källa</a>', res.text)
        # should be generated by wsgi app
        self.assertEqual("ferenda", res.headers.get("X-WSGI-app"), "%s wasn't served by the WSGI app" % self.baseurl + "sou/2008:5")

# the local dev environment, as specified by
# lagen/nu/res/scripts/testdata.txt, doesn't have all these documents
@unittest.skipIf(":8000" in os.environ.get("FERENDA_TESTURL", "http://localhost:8000"), "Not testing against dev server")
class Regressions(TestLagen):
    # this is really a testcase built from a extensive bug report,
    # containing 9 numbered issues. Some of those are suggestions or
    # otherwise untestable, but the testable things are written as
    # test cases here

    def test_sfs_source(self):
        # issue 1 b
        res = self.get(self.baseurl + "2002:562")
        soup = BeautifulSoup(res.text, "lxml")
        dep = soup.find("dt", text="Departement").find_next_sibling("dd")
        self.assertEqual("Näringsdepartementet RS N", dep.text)

    def test_facsimiles(self):
        # issue 3 
        for urlseg, pages in (("prop/1915:83", [29]), # new kind of repo
                              ("prop/2004/05:147", [36, 48]),
                              ("prop/1997/98:177", [18, 30, 32]),
                              ("prop/1997/98:179", [57, 58, 43]),
                              ("prop/2007/08:95", [56, 295, 296]),
                              ("prop/1998/99:90", [18, 23]),
                              ("prop/1996/97:141", [19]),
                              ("prop/1996/97:106", [22]), # based on index.wpd, not a PDF
                              ("sou/1944:59", [15]),
                              ("sou/1944:49", [15]),
                              ("prop/1978/79:11", [15]), 
                              ("prop/2008/09:14", [15]),
                              ("prop/2011/12:115", [15]),
                              ("prop/1980/81:44", [15]),
                              ("prop/1996/97:9", [1]),
        ):
            for page in pages:
                url = self.baseurl + urlseg + "/sid%s.png" % page
                self.assert200(url)

    def test_format(self):
        # issue 4
        for urlseg in ("prop/1994/95:76",
                       "prop/1994/95:93",
                       "prop/1994/95:89",
                       "prop/1994/95:102",
                       "prop/1994/95:115",
                       "prop/1993/94:65",
                       "prop/1993/94:67",
                       "prop/1993/94:242"):
            res = self.get(self.baseurl + urlseg)
            res.raise_for_status()
            self.assertTrue("<pre>" not in res.text)

    def test_missing_pages(self):
        # issue 5: "I prop. 1992/93:30 saknas s. 18–30. Prop. 1996/97:106 är ofullständig (har bara två sidor)"
        #
        # added: I SOU 2002:18 saknas s. 6–15. I SOU 1997:58 saknas s. 6 och 7.
        for urlseg, expected_missing in (
                ("prop/1992/93:30", []),
                ("prop/1996/97:106", [3, ]),
                ("sou/2002:18", []),  # should be [6,7,8,9,10,11,12,13,14] once we identify and omit the TOC
                ("sou/1997:58", [1,2,6,7])
                # more to do:
                # Prop. 1995/96:115 är ofullständig.
                # I prop. 1983/84:78 är sidnumreringen fel fr.o.m. s. 12 (som har fått sidnummer 21).
                # I prop. 2008/09:67 är sidnumreringen fel och saknas s. 4–7.
                # I Ds 2002:56 är sidnumreringen fel.
                # I prop. 1996/97:9 saknas bildfiler och verkar det vara något konstigt med sidnumreringen.
                # I SOU 1997:44 är det fel på s. 5 (den skannade texten är annan än den på bilden) och s. 6–9 saknas.
                ):
            res = self.get(self.baseurl + urlseg)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "lxml")
            pages = soup.find_all("div", "sida")
            # any prop should have at least 10 pages
            self.assertGreater(len(pages), 10)
            # make sure there are no missing pages (except those we
            # expect to be missing, due to them being TOC pages)
            pagenum = 1
            for page in pages:
                while pagenum in expected_missing:
                    pagenum += 1
                self.assertEqual(str(pagenum), page.get("id")[3:], urlseg)
                pagenum += 1

    def test_missing_docs(self):
        # issue 6
        for urlseg in ("prop/1992/93:40",  # left out by design since noone refers to it
                       "prop/1991/92:155", # left out by design since noone refers to it
                       "prop/1973:90",
                       "prop/1996/97:72",
                       "prop/1995/96:79",  # left out by design since noone refers to it
                       # "prop/2007/08:85",  # does this one even exist?
                       "dir/1989:50",     # requested, but had parsing errors
                       "prop/2004/05:17", # requested, but had parsing errors
                       
        ):
            self.assert200(self.baseurl + urlseg)

    def test_doc_version(self):
        # Av SOU 2009:44 fanns tidigare bara den engelska sammanfattningen med.
        for urlseg, expected_title in (
                ("sou/2009:44", "Integritetsskydd i arbetslivet"),
                ):
            res = self.get(self.baseurl + urlseg + ".rdf")
            res.raise_for_status()
            # once that gets working:
            # 1 load into a rdflib graph,
            # 2 find root,
            # 3 get dcterms:title,
            # 4 compare to expected_title
        

    def test_identifier_formats(self):
        # issue 7
        for urlseg in ("dir/1987:42",
                       "dir/1987:7"):
            res = self.get(self.baseurl + urlseg)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "lxml")
            # directly underneath <article> there should be no nodes w/o class "row"
            for node in soup.find("article").children:
                if isinstance(node, str):
                    continue
                self.assertIn("row", node.get("class", []))

    tocs = (("dir", 1987, "^Dir\. (19|20)\d{2}:[1-9]\d{,2}$"),
            ("ds", 2001, "^Ds (19|20)\d{2}:[1-9]\d{,2}$"), # first published is from 1995 but published coverage the first few years is spotty 
            ("sou", 1922, "^SOU (19|20)\d{2}:[1-9]\d{,2}$"),
            ("prop", 1971, "^Prop\. (19|20)\d{2}(|/\d{2}|/2000):[1-9]\d{,2}$"))

    def test_toc(self):
        # issue 8
        errors = []
        for doctype, startyear, regex in self.tocs:
            for year in range(startyear, 2018):
                if doctype == "prop" and year > 1975:
                    nextyear = "2000" if year == 2000 else str(year)[2:]
                    year = "%s/%s" % (year - 1, nextyear)
                url = "dataset/forarbeten?%s=%s" % (doctype, year)
                res = self.get(self.baseurl + url)
                res.raise_for_status()
                soup = BeautifulSoup(res.text, "lxml")
                links = 0
                for idx, link in enumerate(soup.find("article").find_all("a")):
                    # self.assertRegexpMatches(link.text, regex)
                    if not re.match(regex, link.text):
                        errors.append("%s/%s: %s (%s)" % (doctype, year, link.text, link.get("href")))
        self.maxDiff = None
        self.assertEqual([], errors)

    def test_toc_coverage(self):
        errors = []
        for doctype, startyear, regex in self.tocs:
            for year in range(startyear, 2018):
                if doctype == "prop" and year > 1975:
                    nextyear = "2000" if year == 2000 else str(year)[2:]
                    year = "%s/%s" % (year - 1, nextyear)
                url = "dataset/forarbeten?%s=%s" % (doctype, year)
                res = self.get(self.baseurl + url)
                res.raise_for_status()
                soup = BeautifulSoup(res.text, "lxml")
                links = soup.find("article").find_all("a") 
                link = links[-1]
                maxidx = int(re.search("\:(\d+)$", link.text).group(1))
                # no more than 10 % of indexes may be missing
                coverage = (len(links)+1)/maxidx
                # propositioner shares a ordinal series with
                # skrivelser (which we don't include, and which can be
                # up to a third of total output per year), so we need to
                # lower our coverage expectations
                expected_coverage = 0.65 if doctype == "prop" else 0.9
                if coverage < expected_coverage:
                    errors.append("%s/%s: coverage %s" % (doctype, year, coverage))
                    # self.assertGreaterEqual(coverage, 0.9, url)
        self.maxDiff = None
        self.assertEqual([], errors)

    # and some other bugs described in a second mail.

    # 1. SOU 1995:149, SOU 2004:23, SOU 2006:22, SOU 2014:49,
    # prop. 2009/10:165, prop. 2013/14:198 och prop. 2009/10:160
    # saknar bildfiler, t.ex. s. 15.
    # 
    # the issue is that links to facsimile pages are
    # incorrectly-relative ("2014:49/sid3.png" instead of
    # "/sou/2014:49/sid3.png")
    def test_facsimile_links(self):
        for urlseg in ("sou/1995:149", "sou/2004:23", "sou/2006:22",
                       "sou/2014:49", "prop/2009/10:165", "prop/2013/14:198",
                       "prop/2009/10:160"):
            res = self.get(self.baseurl + urlseg)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "lxml")
            found = False
            for a in soup.find_all("a", "facsimile"):
                found = True
                self.assertIn(urlseg, a.get("href"))
                self.assertIn(urlseg, a.img.get("data-src"))
            self.assertTrue(found, urlseg)

class AcceptableStatus(TestLagen):

    def test_status(self):
        def assert_stats(line, maxfail, maxwarn, repo="toplevel"):
            m = re.match(r"(\d+) % failed,\s*(\d+) % warnings", line)
            fail, warn = m.groups()
            self.assertLessEqual(int(fail), maxfail, "%s has more than %s %% fails" % (repo, maxfail))
            self.assertLessEqual(int(warn), maxwarn, "%s has more than %s %% warns" % (repo, maxwarn))
            
        res = self.get(self.baseurl + "status/status.html")
        soup = BeautifulSoup(res.text, "lxml")

        # 1 make sure h1.small is at most a day old
        gentime = datetime.strptime(soup.find("h1").small.text.strip()[:19],
                                    "%Y-%m-%dT%H:%M:%S")
        days = (datetime.now() - gentime).days
        self.assertLessEqual(days, 76)

        # 2 make sure total fail < 3 %, warnings < 20 %
        stats = soup.select("p > small")
        assert_stats(stats.pop(0).text, 3, 20)

        # 3 make sure that for each repo, fail < 6 %, warnings < 65 % (yeah this should be lower but myndfs...)
        for s in stats:
            repo = s.parent.find_previous_sibling("h2").text
            assert_stats(s.text, 6, 65, repo)
        
    
    
