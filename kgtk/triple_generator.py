import sys
import re
from typing import TextIO
from kgtk.exceptions import KGTKException
from etk.wikidata.entity import WDItem, WDProperty
from etk.etk_module import ETKModule
from etk.etk import ETK
from etk.knowledge_graph import KGSchema
from etk.wikidata import wiki_namespaces
from etk.wikidata.value import ( 
Precision,
Item,
StringValue,
TimeValue,
QuantityValue,
MonolingualText,
GlobeCoordinate,
ExternalIdentifier,
URLValue
)


class TripleGenerator:
    """
    A class to maintain the status of the generator
    """
    def __init__(
        self,
        prop_file: str,
        label_set: str,
        alias_set: str,
        description_set: str,
        ignore: bool,
        n: int,
        dest_fp: TextIO = sys.stdout,
        truthy:bool =False
    ):
        from etk.wikidata.statement import Rank
        self.ignore = ignore
        self.prop_types = self.set_properties(prop_file)
        self.label_set, self.alias_set, self.description_set = self.set_sets(
            label_set, alias_set, description_set
        )
        self.fp = dest_fp
        self.n = int(n)
        self.read_num_of_lines = 0
        # ignore-logging, if not ignore, log them and move on.
        if not self.ignore:
            self.ignore_file = open("ignored.log","w")
        # corrupted statement id
        self.corrupted_statement_id = None
        # truthy
        self.truthy = truthy        
        self.reset_etk_doc()
        self.serialize_prefix()
    
    def _node_2_entity(self, node:str):
        '''
        A node can be Qxxx or Pxxx, return the proper entity.
        '''
        if node in self.prop_types:
            entity = WDProperty(node, self.prop_types[node])
        else:
            entity = WDItem(TripleGenerator.replaceIllegalString(node.upper()))
        return entity


    def set_properties(self, prop_file: str):
        datatype_mapping = {
            "item": Item,
            "time": TimeValue,
            "globe-coordinate": GlobeCoordinate,
            "quantity": QuantityValue,
            "monolingualtext": MonolingualText,
            "string": StringValue,
            "external-identifier":ExternalIdentifier,
            "url":URLValue
        }
        with open(prop_file, "r") as fp:
            props = fp.readlines()
        prop_types = {}
        for line in props[1:]:
            node1, _, node2 = line.split("\t")
            try:
                prop_types[node1] = datatype_mapping[node2.strip()]
            except:
                if not self.ignore:                    
                    raise KGTKException(
                        "DataType {} of node {} is not supported.\n".format(
                            node2, node1
                        )
                    )
        return prop_types

    def set_sets(self, label_set: str, alias_set: str, description_set: str):
        return (
            set(label_set.split(",")),
            set(alias_set.split(",")),
            set(description_set.split(",")),
        )

    def reset_etk_doc(self, doc_id: str = "http://isi.edu/default-ns/projects"):
        """
        reset the doc object and return it. Called at initialization and after outputting triples.
        """
        kg_schema = KGSchema()
        kg_schema.add_schema("@prefix : <http://isi.edu/> .", "ttl")
        self.etk = ETK(kg_schema=kg_schema, modules=ETKModule)
        self.doc = self.etk.create_document({}, doc_id=doc_id)
        for k, v in wiki_namespaces.items():
            self.doc.kg.bind(k, v) 
    
    def serialize(self):
        """
        Seriealize the triples. Used a hack to avoid serializing the prefix again.
        """
        docs = self.etk.process_ems(self.doc)
        self.fp.write("\n\n".join(docs[0].kg.serialize("ttl").split("\n\n")[1:]))
        self.fp.flush()
        self.reset()

    def serialize_prefix(self):
        """
        This function should be called only once after the doc object is initialized.
        In order to serialize the prefix at the very begining it has to be printed per the change of rdflib 4.2.2->5.0.0
        Relevent issue: https://github.com/RDFLib/rdflib/issues/965
        """
        for k, v in wiki_namespaces.items():
            line = "@prefix " + k + " " + v + " .\n" 
            self.fp.write(line)
        self.fp.write("\n")
        self.fp.flush()
        self.reset()

    def reset(self):
        self.to_append_statement_id = None
        self.to_append_statement = None
        self.read_num_of_lines = 0
        self.reset_etk_doc()

    def finalize(self):
        self.serialize()

    @staticmethod
    def process_text_string(string:str)->[str,str]:
        ''' 
        '''
        if "@" in string:
            res = string.split("@")
            text_string = "@".join(res[:-1]).replace('"', "").replace("'", "")
            lang = res[-1].replace('"','').replace("'","")
            if len(lang) != 2:
                lang = "en"
        else:
            text_string = string.replace('"', "").replace("'", "")
            lang = "en"
        return [text_string, lang]

    def generate_label_triple(self, node1: str, label: str, node2: str) -> bool:
        entity = self._node_2_entity(node1)
        text_string, lang = TripleGenerator.process_text_string(node2)
        entity.add_label(text_string, lang=lang)
        self.doc.kg.add_subject(entity)
        return True

    def generate_description_triple(self, node1: str, label: str, node2: str) -> bool:
        entity = self._node_2_entity(node1)
        text_string, lang = TripleGenerator.process_text_string(node2)
        entity.add_description(text_string, lang=lang)
        self.doc.kg.add_subject(entity)
        return True

    def generate_alias_triple(self, node1: str, label: str, node2: str) -> bool:
        entity = self._node_2_entity(node1)
        text_string, lang = TripleGenerator.process_text_string(node2)
        entity.add_alias(text_string, lang=lang)
        self.doc.kg.add_subject(entity)
        return True

    def generate_prop_declaration_triple(self, node1: str, label: str, node2: str) -> bool:
        prop = WDProperty(node1, self.prop_types[node1])
        self.doc.kg.add_subject(prop)
        return True

    def generate_normal_triple(
        self, node1: str, label: str, node2: str, is_qualifier_edge: bool) -> bool:
        entity = self._node_2_entity(node1)
        # determine the edge type
        edge_type = self.prop_types[label]
        if edge_type == Item:
            object = WDItem(TripleGenerator.replaceIllegalString(node2.upper()))
        elif edge_type == TimeValue:
            # https://www.wikidata.org/wiki/Help:Dates
            # ^2013-01-01T00:00:00Z/11
            # ^8000000-00-00T00:00:00Z/3
            if re.compile("[0-9]{4}").match(node2):
                try:                   
                    dateTimeString = node2 + "-01-01"
                    object = TimeValue(
                        value=dateTimeString, #TODO
                        calendar=Item("Q1985727"),
                        precision=Precision.year,
                        time_zone=0,
                    )
                except:
                    return False
            else:
                try:
                    dateTimeString, precision = node2[1:].split("/")
                    dateTimeString = dateTimeString[:-1] # remove "Z"
                    # 2016-00-00T00:00:00 case
                    if "-00-00" in dateTimeString:
                        dateTimeString = "-01-01".join(dateTimeString.split("-00-00"))
                    elif dateTimeString[8:10] == "00":
                        dateTimeString = dateTimeString[:8]+"01" + dateTimeString[10:]
                    object = TimeValue(
                        value=dateTimeString,
                        calendar=Item("Q1985727"),
                        precision=precision,
                        time_zone=0,
                    )
                except: 
                    return False

            #TODO other than that, not supported. Creation of normal triple fails
            

        elif edge_type == GlobeCoordinate:
            latitude, longitude = node2[1:].split("/")
            object = GlobeCoordinate(
                latitude, longitude, 0.0001, globe=StringValue("Earth")
            )

        elif edge_type == QuantityValue:
            # +70[+60,+80]Q743895
            res = re.compile("([\+|\-]?[0-9]+\.?[0-9]*)(?:\[([\+|\-]?[0-9]+\.?[0-9]*),([\+|\-]?[0-9]+\.?[0-9]*)\])?([U|Q](?:[0-9]+))?").match(node2).groups()
            amount, lower_bound, upper_bound, unit = res

            # Handle extra small numbers for now. TODO
            if TripleGenerator.is_invalid_decimal_string(amount) or TripleGenerator.is_invalid_decimal_string(lower_bound) or TripleGenerator.is_invalid_decimal_string(upper_bound):
                return False
            amount = TripleGenerator.clean_number_string(amount)
            lower_bound = TripleGenerator.clean_number_string(lower_bound)
            upper_bound = TripleGenerator.clean_number_string(upper_bound)
            if unit != None:
                if upper_bound != None and lower_bound != None:
                    object = QuantityValue(amount, unit=Item(unit),upper_bound=upper_bound,lower_bound=lower_bound)
                else:
                    object = QuantityValue(amount, unit=Item(unit))
            else:
                if upper_bound != None and lower_bound != None:
                    object = QuantityValue(amount, upper_bound=upper_bound,lower_bound=lower_bound)
                else:
                    object = QuantityValue(amount)                   
        elif edge_type == MonolingualText:
            text_string, lang = TripleGenerator.process_text_string(node2)
            object = MonolingualText(text_string, lang)
        elif edge_type == ExternalIdentifier:
            object = ExternalIdentifier(node2)
        elif edge_type == URLValue:
            object = URLValue(node2)
        else:
            # treat everything else as stringValue
            object = StringValue(node2)
        if is_qualifier_edge:
            # edge: e8 p9 ^2013-01-01T00:00:00Z/11
            # create qualifier edge on previous STATEMENT and return the updated STATEMENT
            if type(object) == WDItem:
                self.doc.kg.add_subject(object)
            self.to_append_statement.add_qualifier(label.upper(), object)
            self.doc.kg.add_subject(self.to_append_statement) #TODO maybe can be positioned better for the edge cases.

        else:
            # edge: q1 p8 q2 e8
            # create brand new property edge and replace STATEMENT
            if type(object) == WDItem:
                self.doc.kg.add_subject(object)
            if self.truthy:
                self.to_append_statement = entity.add_truthy_statement(label.upper(), object) 
            else:
                self.to_append_statement = entity.add_statement(label.upper(), object) 
            self.doc.kg.add_subject(entity)
        return True
    
    @staticmethod
    def is_invalid_decimal_string(num_string):
        '''
        if a decimal string too small, return True TODO
        '''
        if num_string == None:
            return False
        else:
            if abs(float(num_string)) < 0.0001 and float(num_string) != 0:
                return True
            return False        

    @staticmethod
    def clean_number_string(num):
        from numpy import format_float_positional
        if num == None:
            return None
        else:
            return format_float_positional(float(num),trim="-")

    def entry_point(self, line_number:int , edge: str):
        """
        generates a list of two, the first element is the determination of the edge type using corresponding edge type
        the second element is a bool indicating whether this is a valid property edge or qualifier edge.
        Call corresponding downstream functions
        """
        edge_list = edge.strip().split("\t")
        l = len(edge_list)
        if l!=4:
            return

        [node1, label, node2, e_id] = edge_list
        node1, label, node2, e_id = node1.strip(),label.strip(),node2.strip(),e_id.strip()
        if line_number == 0: #TODO ignore header mode
            # by default a statement edge
            is_qualifier_edge = False
            # print("#Debug Info: ",line_number, self.to_append_statement_id, e_id, is_qualifier_edge,self.to_append_statement)
            self.to_append_statement_id = e_id
            self.corrupted_statement_id = None
        else:
            if node1 != self.to_append_statement_id:
                # also a new statement edge
                if self.read_num_of_lines >= self.n:
                    self.serialize()
                is_qualifier_edge = False
                # print("#Debug Info: ",line_number, self.to_append_statement_id, node1, is_qualifier_edge,self.to_append_statement)
                self.to_append_statement_id= e_id
                self.corrupted_statement_id = None
            else:
            # qualifier edge or property declaration edge
                is_qualifier_edge = True
                if self.corrupted_statement_id == e_id:
                    # Met a qualifier which associates with a corrupted statement
                    return
                if label != "type" and node1 != self.to_append_statement_id:
                    # 1. not a property declaration edge and
                    # 2. the current qualifier's node1 is not the latest property edge id, throw errors.
                    if not self.ignore:
                        raise KGTKException(
                            "Node1 {} at line {} doesn't agree with latest property edge id {}.\n".format(
                                node1, line_number, self.to_append_statement_id
                            )
                        )
        if label in self.label_set:
            success = self.generate_label_triple(node1, label, node2)
        elif label in self.description_set:
            success= self.generate_description_triple(node1, label, node2)
        elif label in self.alias_set:
            success = self.generate_alias_triple(node1, label, node2)
        elif label == "type":
            # special edge of prop declaration
            success = self.generate_prop_declaration_triple(node1, label, node2)
        else:
            if label in self.prop_types:
                success= self.generate_normal_triple(node1, label, node2, is_qualifier_edge)
            else:
                if not self.ignore:
                    raise KGTKException(
                        "property {}'s type is unknown at line {}.\n".format(label, line_number)
                    )
                    success = False
        if (not success) and (not is_qualifier_edge) and (not self.ignore):
            # We have a corrupted edge here.
            self.ignore_file.write("Corrupted statement at line number: {} with id {} with current corrupted id {}\n".format(line_number, e_id, self.corrupted_statement_id))
            self.ignore_file.flush()
            self.corrupted_statement_id = e_id
        else:
            self.read_num_of_lines += 1
            self.corrupted_statement_id = None

    
    @staticmethod
    def replaceIllegalString(s:str)->str:
        return s.replace(":","-")