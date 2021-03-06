# -*- coding: utf-8 -*-
from __future__ import print_function, unicode_literals
__metaclass__ = type
import re
from operator import attrgetter
from rdflib import Graph, Literal, Namespace, URIRef, RDF, RDFS, BNode
from rdflib.resource import Resource
from six.moves.urllib_parse import urljoin
from six import text_type as str

COIN = Namespace("http://purl.org/court/def/2009/coin#")


class URIMinter:

    def __init__(self, config, scheme_uri):
        self.space = URISpace(config.resource(scheme_uri))

    def compute_uris(self, data, reporter=None):
        results = {}
        for s in set(data.subjects()):
            uris = self.space.coin_uris(data.resource(s))
            if uris:
                results[s] = uris
        return results


class URISpace:

    def __init__(self, resource):
        self.base = str(resource.value(COIN.base))
        self.fragmentSeparator = str(resource.value(COIN.fragmentSeparator))
        self.slugTransform = SlugTransformer(resource.value(COIN.slugTransform))
        self.templates = [Template(self, template_resource)
                          for template_resource in resource.objects(
                                  COIN.template)]
        # primary sort order by :priority
        # secondary sort by type specificity (wether a self.forType is specified)
        # tertiary sort order by specificity (number of vars per template)
        self.templates.sort(key=lambda x: (x.priority, x.forType, len(x.bindings)),
                            reverse=True) 

    def coin_uris(self, resource):
        for template in self.templates:
            uri = template.coin_uri(resource)
            if uri:
                yield uri

    def coin_uri(self, resource):
        assert isinstance(resource, Resource), "coin_uri got a %s object, not a rdflib.resource.Resource" % type(resource)
        try:
            return next(self.coin_uris(resource))
        except StopIteration: 
            raise ValueError("Couldn't mint uri from %s" % resource)


class SlugTransformer:

    def __init__(self, resource):
        self.applyTransforms = resource and list(
                resource.objects(COIN.apply)) or []
        self.replace = resource and replacer(
                resource.objects(COIN['replace'])) or None
        # NB: we must allow for spaceReplacement to be set to ""
        self.spaceRepl = resource and resource.value(
                COIN.spaceReplacement)
        if self.spaceRepl is None:
            self.spaceRepl = u'+'
        self.stripPattern = resource and re.compile(
                str(resource.value(COIN.stripPattern))) or None

    def __call__(self, value):
        value = str(value)
        for transform in self.applyTransforms:
            if transform.identifier == COIN.ToLowerCase:
                value = value.lower()
            else:
                #raise NotImplementedError(
                #        u"URIMinter doesn't support the <%s> transform" %
                #        transform.identifier)
                pass
        if self.replace:
            value = self.replace(value)
        if self.spaceRepl is not None:
            value = value.replace(" ", self.spaceRepl)
        if self.stripPattern:
            value = self.stripPattern.sub(u'', value)
        return value


def replacer(replacements):
    char_pairs = [str(repl).split(u' ') for repl in replacements]
    def replace(value):
        for char, repl in char_pairs:
            value = value.replace(char, repl)
        return value
    return replace


class Template:

    def __init__(self, space, resource):
        self.space = space
        self.resource = resource
        self.priority = int(resource.value(COIN.priority) or 0)
        self.forType = resource.value(COIN.forType)
        self.uriTemplate = resource.value(COIN.uriTemplate)
        self.fragmentTemplate = resource.value(COIN.fragmentTemplate)
        self.relToBase = resource.value(COIN.relToBase)
        self.relFromBase = resource.value(COIN.relFromBase)
        self.bindings = [Binding(self, binding)
                for binding in resource.objects(COIN.binding)]
        # IMPROVE: if not template and variable bindings correspond: TemplateException
        assert self.uriTemplate or self.fragmentTemplate, "No template for template"

        # If there's a special slug transform defined for this
        # template, use that, otherwise use the one defined for the
        # entire URISpace
        if resource.value(COIN.slugTransform):
            self.slugTransform = SlugTransformer(resource.value(COIN.slugTransform))
        else:
            self.slugTransform = space.slugTransform

    def __repr__(self):
        if self.uriTemplate:
            return "<Template %s>" % self.uriTemplate
        elif self.fragmentTemplate:
            return "<Template #%s>" % self.fragmentTemplate
        else:
            return "<Template>"

    def coin_uri(self, resource):
        # self.forType is bound to the space graph, resource is bound
        # to the content graph so we can't just compare graphs
        # if self.forType and not self.forType in resource.objects(RDF.type):
        if self.forType and self.forType.identifier not in [
                x.identifier for x in resource.objects(RDF.type)]:
            return None
        matches = {}
        for binding in self.bindings:
            match = binding.find_match(resource)
            if match:
                matches[binding.variable] = match
        if len(matches) < len(self.bindings):
            return None
        # IMPROVE: store and return partial success (for detailed feedback)
        return self.build_uri(self.get_base(resource), matches)

    def build_uri(self, base, matches):
        if not base:
            return None
        if self.uriTemplate:
            expanded = str(self.uriTemplate)
        elif self.fragmentTemplate:
            if "#" in base:
                base += self.space.fragmentSeparator
            else:
                base += "#"
            expanded = base + str(self.fragmentTemplate)
        else:
            return None

        expanded = expanded.replace("{+base}", base)
        for var, value in matches.items():
            slug = self.transform_value(value)
            expanded = expanded.replace("{%s}" % var, slug)
        # if base is eg "http://localhost/res/" and expanded is a
        # /-prefixed relative uri like "/sfs/9999:998", urljoin
        # results in "http://localhost/sfs/9999:998/", not
        # "http://localhost/res/" like you'd expect. So we work
        # around.
        if expanded[0] == "/":
            expanded = expanded[1:]
            
        if expanded.startswith("http://") or expanded.startswith("https://"):
            return urljoin(base, expanded)
        else:
            # see the test integrationLegalURI.CustomCoinstruct.test_1845_50_s.1
            return "%s/%s" % (base, expanded)

    def get_base(self, resource):
        base = self.space.base
        def guarded_base(b):
            s = str(b.identifier)
            if isinstance(b.identifier, URIRef) and s.startswith(base):
                return s
            elif isinstance(b.identifier, (BNode, URIRef)):
                # try to recursively mint a URI for this other subject
                try:
                    return self.space.coin_uri(b)
                except ValueError:  # FIXME: mk coin_uri raise specific error
                    return None
            else:
                return None
        if self.relToBase:
            for baserel in resource.objects(self.relToBase.identifier):
                return guarded_base(baserel)
        elif self.relFromBase:
            for baserev in resource.subjects(self.relFromBase.identifier):
                return guarded_base(baserev)
        else:
            return base

    def transform_value(self, value):
        return self.slugTransform(value)

class Binding:

    def __init__(self, template, resource):
        self.template = template
        self.p = resource.value(COIN.property).identifier
        self.variable = resource.value(COIN.variable) or uri_leaf(self.p)
        self.slugFrom = resource.value(COIN.slugFrom)
        self.match = resource.value(COIN.match)

    def __repr__(self):
        return "<Binding %s>" % self.template.resource.graph.qname(self.p)

    def find_match(self, resource):
        value = resource.value(self.p)
        if self.slugFrom:
            if not value:
                return None
            if value.value(self.slugFrom.identifier):
                # the graph from where value is taken might contain only
                # metadata about the resource, not the database of slugs.
                value = value.value(self.slugFrom.identifier)
            else:
                # as a fallback, look for the slug in the space graph.
                space = self.template.resource.graph.resource(value.identifier)
                value = space.value(self.slugFrom.identifier)

        if self.match and value != self.match:
            return None
        else:
            return value


def uri_leaf(uri):
    for char in ('#', '/', ':'):
        if uri.endswith(char):
            break
        base, sep, leaf = uri.rpartition(char)
        if sep and leaf:
            return leaf


if __name__ == '__main__':

    from sys import argv
    args = argv[1:]
    space_data = args.pop(0)
    sources = args

    from mimetypes import guess_type
    def parse_file(graph, fpath):
        graph.parse(fpath, format=guess_type(fpath)[0] or 'n3')

    coin_graph = Graph()
    parse_file(coin_graph, space_data)
    instance_data = Graph() if sources else coin_graph
    for source in sources:
        parse_file(instance_data, source)

    for space_uri in coin_graph.subjects(RDF.type, COIN.URISpace):
        print("URI Space <%s>:" % space_uri)
        minter = URIMinter(coin_graph, space_uri)
        for subj, uris in minter.compute_uris(instance_data).items():
            if str(subj) in uris:
                print("Found <%s> in" % subj,)
            else:
                print("Did not find <%s> in" % subj,)
            print(", ".join(("<%s>" % uri) for uri in uris))


