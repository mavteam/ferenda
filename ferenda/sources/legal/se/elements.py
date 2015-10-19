# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function

from lxml.builder import ElementMaker
from six import text_type as str

from ferenda.elements import (CompoundElement, OrdinalElement,
                              TemporalElement, UnicodeElement, Link,
                              Paragraph, Section, SectionalElement)

E = ElementMaker(namespace="http://www.w3.org/1999/xhtml")

class Forfattning(CompoundElement, TemporalElement):
    """Grundklass för en konsoliderad författningstext."""
    tagname = "body"
    classname = "konsolideradforfattning"

# Rubrik är en av de få byggstenarna som faktiskt inte kan innehålla
# något annat (det förekommer "aldrig" en hänvisning i en
# rubriktext). Den ärver alltså från UnicodeElement, inte
# CompoundElement.
class Rubrik(UnicodeElement, TemporalElement):
    """En rubrik av något slag - kan vara en huvud- eller underrubrik
    i löptexten, en kapitelrubrik, eller något annat"""

    def _get_tagname(self):
        if hasattr(self, 'type') and self.type == "underrubrik":
            return "h3"
        else:
            return "h2"
    tagname = property(_get_tagname, "Docstring here")

    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Rubrik, self).__init__(*args, **kwargs)


class Stycke(CompoundElement):
    fragment_label = "S"
    tagname = "p"
    typeof = "rinfoex:Stycke"  # not defined by the rpubl vocab

    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Stycke, self).__init__(*args, **kwargs)


class Strecksatslista (CompoundElement):
    tagname = "ul"
    classname = "strecksatslista"


class NumreradLista (CompoundElement):
    tagname = "ul"  # These list are not always monotonically
    # increasing, which a <ol> requrires
    classname = "numreradlista"


class Bokstavslista (CompoundElement):
    tagname = "ul"  # See above
    classname = "bokstavslista"


class Tabell(CompoundElement):
    tagname = "table"


class Tabellrad(CompoundElement, TemporalElement):
    tagname = "tr"


class Tabellcell(CompoundElement):
    tagname = "td"


class Avdelning(CompoundElement, OrdinalElement):
    tagname = "div"
    fragment_label = "A"

    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Avdelning, self).__init__(*args, **kwargs)


class UpphavtKapitel(UnicodeElement, OrdinalElement):
    """Ett UpphavtKapitel är annorlunda från ett upphävt Kapitel på så
    sätt att inget av den egentliga lagtexten finns kvar, bara en
    platshållare"""


class Kapitel(CompoundElement, OrdinalElement):
    fragment_label = "K"
    tagname = "div"
    typeof = "rpubl:Kapitel"  # FIXME: This is qname string, not
    # rdflib.URIRef (which would be better), since as_xhtml doesn't
    # have access to a graph with namespace bindings, which is
    # required to turn a URIRef to a qname
    
    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Kapitel, self).__init__(*args, **kwargs)


class UpphavdParagraf(UnicodeElement, OrdinalElement):
    pass


# en paragraf har inget "eget" värde, bara ett nummer och ett eller
# flera stycken
class Paragraf(CompoundElement, OrdinalElement):
    fragment_label = "P"
    tagname = "div"
    typeof = "rpubl:Paragraf"  # FIXME: see above

    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Paragraf, self).__init__(*args, **kwargs)


# kan innehålla nästlade numrerade listor
class Listelement(CompoundElement, OrdinalElement):
    fragment_label = "N"
    tagname = "li"

    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Listelement, self).__init__(*args, **kwargs)


class Overgangsbestammelser(CompoundElement):

    def __init__(self, *args, **kwargs):
        self.rubrik = kwargs.get('rubrik', 'Övergångsbestämmelser')
        super(Overgangsbestammelser, self).__init__(*args, **kwargs)


class Overgangsbestammelse(CompoundElement, OrdinalElement):
    tagname = "div"
    fragment_label = "L"

    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Overgangsbestammelse, self).__init__(*args, **kwargs)


class Bilaga(CompoundElement):
    fragment_label = "B"

    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Bilaga, self).__init__(*args, **kwargs)


class Register(CompoundElement):
    """Innehåller lite metadata om en grundförfattning och dess
    efterföljande ändringsförfattningar"""
    tagname = "div"
    classname = "register"

    def __init__(self, *args, **kwargs):
        self.rubrik = kwargs.get('rubrik', None)
        super(Register, self).__init__(*args, **kwargs)

    def as_xhtml(self, uri=None, parent_uri=None):
        res = super(Register, self).as_xhtml()
        res.insert(0, E('h1', self.rubrik))
        return res


class Registerpost(CompoundElement):

    """Metadata for a particular Grundforfattning or Andringsforfattning in the form of a rdflib graph, optionally with a Overgangsbestammelse."""
    tagname = "div"
    classname = "registerpost"

    def __init__(self, *args, **kwargs):
        self.id = kwargs.get("id", None)
        self.uri = kwargs.get("uri", None)
        super(Registerpost, self).__init__(*args, **kwargs)

    def as_xhtml(self, uri=None, parent_uri=None):
        # FIXME: Render this better (particularly the rpubl:andring
        # property -- should be parsed and linked)
        return super(Registerpost, self).as_xhtml()

class OrderedParagraph(Paragraph, OrdinalElement):

    def as_xhtml(self, baseuri, parent_uri=None):
        element = super(OrderedParagraph, self).as_xhtml(baseuri, parent_uri)
        # FIXME: id needs to be unique in document by prepending a
        # instans identifier
        # element.set('id', self.ordinal)
        return element


class DomElement(CompoundElement):
    tagname = "div"
    prop = None

    def _get_classname(self):
        return self.__class__.__name__.lower()
    classname = property(_get_classname)

    def as_xhtml(self, baseuri, parent_uri=None):
        element = super(DomElement, self).as_xhtml(baseuri, parent_uri)
        if self.prop:
            # ie if self.prop = ('ordinal', 'dcterms:identifier'), then
            # dcterms:identifier = self.ordinal
            if (hasattr(self, self.prop[0]) and
                    getattr(self, self.prop[0]) and
                    isinstance(getattr(self, self.prop[0]), str)):
                element.set('content', getattr(self, self.prop[0]))
                element.set('property', self.prop[1])
        return element


class Delmal(DomElement):
    prop = ('ordinal', 'dcterms:identifier')


class Instans(DomElement):
    prop = ('court', 'dcterms:creator')


class Dom(DomElement):
    prop = ('malnr', 'dcterms:identifier')


class Domskal(DomElement):
    pass


class Domslut(DomElement):
    pass  # dcterms:author <- names of judges


class Betankande(DomElement):
    pass  # dcterms:author <- referent


class Skiljaktig(DomElement):
    pass  # dcterms:author <- name


class Tillagg(DomElement):
    pass  # dcterms:author <- name


class Endmeta(DomElement):
    pass

class AnonSektion(CompoundElement):
    tagname = "div"

class Abstract(CompoundElement):
    tagname = "div"
    classname = "beslutikorthet"


class Blockquote(CompoundElement):
    tagname = "blockquote"


class Meta(CompoundElement):
    pass

class Stycke(Paragraph):
    pass


class Sektion(Section):
    pass


class Sidbrytning(OrdinalElement):
    def as_xhtml(self, uri, parent_uri=None):
        return E("span", {'id': 'sid%s' % self.ordinal,
                          'class': 'sidbrytning'})


class PreambleSection(CompoundElement):
    tagname = "div"
    classname = "preamblesection"
    counter = 0
    uri = None

    def as_xhtml(self, uri, parent_uri=None):
        if not self.uri:
            self.__class__.counter += 1
            self.uri = uri + "#PS%s" % self.__class__.counter
        element = super(PreambleSection, self).as_xhtml(uri, parent_uri)
        element.set('property', 'dcterms:title')
        element.set('content', self.title)
        element.set('typeof', 'bibo:DocumentPart')
        return element


class UnorderedSection(CompoundElement):
    # FIXME: It'd be nice with some way of ordering nested unordered
    # sections, like:
    #  US1
    #  US2
    #    US2.1
    #    US2.2
    #  US3
    #
    # right now they'll appear as:
    #  US1
    #  US2
    #    US3
    #    US4
    #  US5
    tagname = "div"
    classname = "unorderedsection"
    counter = 0
    uri = None

    def as_xhtml(self, uri, parent_uri=None):
        if not self.uri:
            self.__class__.counter += 1
            # note that this becomes a document-global running counter
            self.uri = uri + "#US%s" % self.__class__.counter
        element = super(UnorderedSection, self).as_xhtml(uri, parent_uri)
        element.set('property', 'dcterms:title')
        element.set('content', self.title)
        element.set('typeof', 'bibo:DocumentPart')
        return element


class Appendix(SectionalElement):
    tagname = "div"
    classname = "appendix"

    def as_xhtml(self, uri, parent_uri=None):
        if not self.uri:
            self.uri = uri + "#B%s" % self.ordinal

        return super(Appendix, self).as_xhtml(uri, parent_uri)


class Coverpage(CompoundElement):
    tagname = "div"
    classname = "coverpage"

