# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division,
                        print_function, unicode_literals)
from builtins import *
import builtins
from copy import copy

from ferenda.elements import Link, LinkSubject

class CitationParser(object):

    """Finds citations to documents and other resources in text
    strings. Each type of citation is specified by a
    `pyparsing <http://pyparsing.wikispaces.com/Documentation>`_
    grammar, and for each found citation a URI can be constructed
    using a :py:class:`~ferenda.URIFormatter` object.

    :param grammars: The grammar(s) for the citations that this
                      parser should find, in order of priority.
    :type  grammars: list of ``pyparsing.ParserElement`` objects

    Usage:

    >>> from pyparsing import Word,nums
    >>> rfc_grammar = ("RFC " + Word(nums).setResultsName("rfcnumber")).setResultsName("rfccite")
    >>> pep_grammar = ("PEP" +  Word(nums).setResultsName("pepnumber")).setResultsName("pepcite")
    >>> citparser = CitationParser(rfc_grammar, pep_grammar)
    >>> res = citparser.parse_string("The WSGI spec (PEP 333) references RFC 2616 (The HTTP spec)")
    >>> # res is a list of strings and/or pyparsing.ParseResult objects
    >>> from ferenda import URIFormatter
    >>> from ferenda.elements import Link
    >>> f = URIFormatter(('rfccite',
    ...                   lambda p: "http://www.rfc-editor.org/rfc/rfc%(rfcnumber)s" % p),
    ...                  ('pepcite',
    ...                   lambda p: "http://www.python.org/dev/peps/pep-0%(pepnumber)s/" % p))
    >>> citparser.set_formatter(f)
    >>> res = citparser.parse_recursive(["The WSGI spec (PEP 333) references RFC 2616 (The HTTP spec)"])
    >>> res == ['The WSGI spec (', Link('PEP 333',uri='http://www.python.org/dev/peps/pep-0333/'), ') references ', Link('RFC 2616',uri='http://www.rfc-editor.org/rfc/rfc2616'), ' (The HTTP spec)']
    True
    """

    def __init__(self, *grammars):
        self._grammars = []
        for grammar in grammars:
            self.add_grammar(grammar)
        self._formatter = None

    def set_formatter(self, formatter):
        """Specify how found citations are to be formatted when using
        :py:meth:`~ferenda.CitationParser.parse_recursive`

        :param formatter: The formatter object to use for all citations
        :type  formatter: :py:class:`~ferenda.URIFormatter`
        """
        self._formatter = formatter

    def add_grammar(self, grammar):
        """Add another grammar.

        :param grammar: The grammar to add
        :type grammar: ``pyparsing.ParserElement``
        """
        self._grammars.append(grammar)

    def parse_string(self, string, predicate="dcterms:references"):
        """Find any citations in a text string, using the configured grammars.

        :param string: Text to parse for citations
        :type string: str
        :returns: strings (for parts of the input text that do not contain
                  any citation) and/or tuples (for found citation) consisting
                  of (string, ``pyparsing.ParseResult``)
        :rtype: list
        """
        # Returns a list of strings and/or tuples, where each tuple is
        # (string,pyparsing.ParseResult)
        nodes = [string]
        res = nodes  # if self._grammars is None
        for grammar in self._grammars:
            res = []
            for node in nodes:
                if not isinstance(node, str):
                    res.append(node)
                    continue
                matches = grammar.scanString(node)
                start = 0
                after = 0
                for match, before, after in matches:
                    if before > start:
                        res.append(node[start:before])
                    res.append((node[before:after], match))
                    start = after
                if after < len(node):
                    res.append(node[after:])
            nodes = list(res)
        return res

    def parse_recursive(self, part, predicate="dcterms:references"):
        """Traverse a nested tree of elements, finding citations in
        any strings contained in the tree. Found citations are marked
        up as :py:class:`~ferenda.elements.Link` elements with the uri
        constructed by the :py:class:`~ferenda.URIFormatter` set by
        :py:meth:`~ferenda.CitationParser.set_formatter`.

        :param part: The root element of the structure to parse
        :type  part: list
        :returns: a correspondingly nested structure.
        :rtype: list"""

        res = []
        if not isinstance(part, str):
            if not (hasattr(part, '__iter__') or
                    hasattr(part, '__getitem__')):
                return part
            for subpart in part:
                if isinstance(subpart, str):
                    res.extend(self.parse_recursive(subpart, predicate))
                else:
                    res.append(self.parse_recursive(subpart, predicate))
            # replace our exising subparts/children with the combined result of
            # parse_recursive
            part[:] = res[:]
            return part

        else:  # ok, simple string
            # FIXME: We need to keep track of the URI for the part
            # of the document we're in, so that we can resolve
            # partial/relative references
            # splits a string into a list of string and ParseResult objects
            #
            nodes = self.parse_string(part, predicate)
            for node in nodes:
                if isinstance(node, str):
                    if isinstance(node, Link):
                        res.append(node)
                    # under py2, str is now really future.types.newstr.newstr
                    elif type(part) == str or (hasattr(builtins, 'unicode') and  # means py2 + future
                                               type(part) == builtins.unicode):
                        res.append(node)
                    else:
                        # handle str-derived types by instantiting
                        # that type and cloning its properties, so:
                        #
                        #     Header("foo 123 baz", lvl=2)
                        #
                        # can result in:
                        #
                        #     [Header("foo ", lvl=2),
                        #      Link("123", uri="..."),
                        #      Header(" baz", lvl=2)]
                        #
                        replacement = type(part)(node)
                        replacement.__dict__ = copy(part.__dict__)
                        res.append(replacement)
                elif isinstance(node, tuple):
                    (text, parseresult) = node
                    # node = self.resolve_relative(node,currentloc)
                    uri = self._formatter.format(parseresult)
                    if uri:
                        res.append(LinkSubject(
                            text, uri=uri, predicate=predicate))
                    else:
                        res.append(text)
                # FIXME: concatenate adjacent str nodes
            return res
