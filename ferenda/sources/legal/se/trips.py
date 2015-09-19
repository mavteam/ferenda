# -*- coding: utf-8 -*-
from __future__ import unicode_literals

# Base class for fetching data from an ancient database system used by
# swedish gov IT...
import re
from six.moves.urllib_parse import quote

import requests
import lxml.html
from bs4 import BeautifulSoup

from ferenda.decorators import downloadmax, recordlastdownload
from ferenda import util
from . import SwedishLegalSource


class NoMoreLinks(Exception):

    def __init__(self, nextpage=None):
        super(NoMoreLinks, self).__init__()
        self.nextpage = nextpage


class Trips(SwedishLegalSource):
    alias = None  # abstract class
    basefile_regex = "(?P<basefile>\d{4}:\d+)$"

    app = None  # komm, dir, prop, sfst
    base = None  # KOMM, DIR, THWALLPROP, SFSR

    source_encoding = "iso-8859-1"

    # NOTE: both SFS and direktiv.DirTrips override this -- hard to find a
    # template that works for everyone
    document_url_template = ("http://rkrattsbaser.gov.se/cgi-bin/thw?"
                             "${HTML}=%(app)s_lst"
                             "&${OOHTML}=%(app)s_doc&${BASE}=%(base)s"
                             "&${TRIPSHOW}=format=THW&BET=%(basefile)s")
    start_url = ("http://rkrattsbaser.gov.se/cgi-bin/thw?${HTML}=%(app)s_lst"
                 "&${OOHTML}=%(app)s_doc&${SNHTML}=%(app)s_err"
                 "&${MAXPAGE}=%(maxpage)d&${TRIPSHOW}=format=THW"
                 "&${BASE}=%(base)s")

    # for SFS
    # start_url = ("http://rkrattsbaser.gov.se/cgi-bin/thw?${HTML}=%(app)s_lst"
    #              "&${OOHTML}=%(app)s_dok&${SNHTML}=%(app)s_err"
    #              "&${MAXPAGE}=%(maxpage)d&${BASE}=%(base)s"
    #             "&${FORD}=FIND&%%C5R=FR%%C5N+%(start)s&%%C5R=TILL+%(end)s")

    download_params = [{'maxpage': 101, 'app': app, 'base': base}]
    # for SFS:
    # download_params = [{'maxpage': 101,
    #                     'app': app,
    #                     'base': base,
    #                     'start': '1600',
    #                     'end': '2008'},
    #                    {'maxpage': 101,
    #                     'app': app,
    #                     'base': base,
    #                     'start': '2009',
    #                     'end': str(datetime.today().year)}]

    def __init__(self, config=None, **kwargs):
        super(Trips, self).__init__(config, **kwargs)
        if self.config.ipbasedurls:
            import socket
            addrs = socket.getaddrinfo("rkrattsbaser.gov.se", 80)
            # grab the first IPv4 number
            ip = [addr[4][0] for addr in addrs if addr[0] == socket.AF_INET][0]
            print("Changing rkrattsbaser.gov.se to %s in all URLs" % ip)
            for p in ('start_url',
                      'document_url_template',
                      'document_sfsr_url_template',
                      'document_sfsr_change_url_template'):
                if hasattr(self, p):
                    setattr(self, p,
                            getattr(self, p).replace('rkrattsbaser.gov.se',
                                                     ip))


    @classmethod
    def get_default_options(cls):
        opts = super(Trips, cls).get_default_options()
        opts['ipbasedurls'] = False
        return opts

    def download(self, basefile=None):
        if basefile:
            return self.download_single(basefile)
        for basefile, url in self.download_get_basefiles(self.download_params):
            self.download_single(basefile, url)

    @downloadmax
    def download_get_basefiles(self, params):
        for param in params:
            done = False
            url = self.start_url % param
            pagecount = 1
            while not done:
                self.log.info("Starting at %s" % url)
                resp = requests.get(url)
                tree = lxml.html.document_fromstring(resp.text)
                tree.make_links_absolute(url, resolve_base_href=True)
                try:
                    for basefile, url in self.download_get_basefiles_page(tree):
                        yield basefile, url
                except NoMoreLinks as e:
                    if e.nextpage:
                        pagecount += 1
                        url = e.nextpage
                        self.log.info("Getting page #%s of results" % pagecount)
                    else:
                        done = True

    def download_get_basefiles_page(self, pagetree):
        nextpage = None
        for element, attribute, link, pos in pagetree.iterlinks():
            if element.text is None:
                continue
            m = re.search(self.basefile_regex, element.text)
            if m:
                basefile = m.group("basefile")
                docurl = link
            else:
                basefile = docurl = None

            if basefile:
                yield(basefile, docurl)
            else:
                # maybe this is the "next page" link?
                m = re.match("Fler poster", element.text)
                if m:
                    nextpage = link
        raise NoMoreLinks(nextpage)

    def download_single(self, basefile, url=None):
        # explicitly call superclass' download_single WITHOUT url
        # parameter. The reason is so that we construct the url
        # through self.remote_url, which provides permanent urls to
        # the wanted documents, instead of the temporary/session id
        # based urls that download_get_basefiles can provide
        return super(Trips, self).download_single(basefile)

    def download_is_different(self, existing, new):
        # load both existing and new into a BeautifulSoup object, then
        # compare the first <pre> element
        existing_soup = BeautifulSoup(
            util.readfile(
                existing,
                encoding=self.source_encoding), "lxml")
        new_soup = BeautifulSoup(util.readfile(new, encoding=self.source_encoding), "lxml")
        return existing_soup.pre != new_soup.pre

    def remote_url(self, basefile):
        return self.document_url_template % {'basefile': quote(basefile),
                                             'app': self.app,
                                             'base': self.base}

    def sanitize_metadata(self, a, basefile):
        a = super(Trips, self).sanitize_metadata(a, basefile)
        a["rpubl:arsutgava"], a["rpubl:lopnummer"] = basefile.split(":")
        return a

