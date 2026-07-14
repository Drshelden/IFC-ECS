# IFCJSON_python - ifc4ingestor_hierarchical.py
# IFC to Hierarchical JSON converter with path-based tree structure
# https://github.com/IFCJSON-Team

# MIT License

from datetime import datetime
import hashlib
import uuid
import json
import sys
import argparse

try:
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.guid as guid
except ImportError as e:
    print(f"Warning: ifcopenshell not available: {e}")
    ifcopenshell = None
    guid = None

from utils import toLowerCamelcase, generateDeterministicGuid, expandGuid

# include empty properties in output (as empty strings) 
INCLUDE_EMPTY_PROPERTIES = False

# Entity types to process in hierarchy
PROCESSABLE_TYPES = {
    'IfcProject',
    'IfcSite',
    'IfcBuilding',
    'IfcBuildingStorey',
    'IfcSpace',
    'IfcElement',
    'IfcWall',
    'IfcWindow',
    'IfcDoor',
    'IfcSlab',
    'IfcColumn',
    'IfcBeam',
    'IfcCovering',
    'IfcFurniture',
    'IfcEquipment',
    'IfcObjectDefinition',
    'IfcPropertySet',
    'IfcRelationship'
}

# Define attributes to exclude
EXCLUDE_ATTRIBUTES = {
    'ownerhistory',
    'id',
    'step_id',
    'objectplacement',
    'representation',
    'representations',
    'representationmaps',
    'representationcontexts',
    'unitsincontext',
    'globalId',
    'decomposedby',
    'iscontainedin',
    'contains',
    'decomposes',
    'isdecomposedby',
}

# Define attribute name substitutions
ATTRIBUTE_SUBSTITUTIONS = {
    'Name': 'componentName',
    'Description': 'componentDescription',
    'HasPropertySets': 'propertySets',
    'type': 'componentType'
}

EXPAND_GUID_ATTRIBUTES = {'GlobalId'}


class IFC2JSONHierarchical:
    """IFC to Hierarchical JSON converter that builds tree structure with paths"""
    
    SCHEMA_VERSION = '0.0.2'

    settings = None  # Lazy-loaded in __init__
    
    def __init__(self, ifcModel, EMPTY_PROPERTIES=False, modelName=None):
        """IFC hierarchical converter

        parameters:
        ifcModel: IFC filePath or ifcopenshell model instance
        EMPTY_PROPERTIES (boolean): if True then empty properties are included
        modelName (str): Optional model name for deterministic GUID generation
        """
        if ifcopenshell is None:
            raise RuntimeError("ifcopenshell is not installed. Cannot process IFC files.")
        
        # Lazy-load settings on first initialization
        if IFC2JSONHierarchical.settings is None:
            IFC2JSONHierarchical.settings = ifcopenshell.geom.settings()
            IFC2JSONHierarchical.settings.set("use-world-coords", True)
        
        if isinstance(ifcModel, ifcopenshell.file):
            self.ifcModel = ifcModel
        else:
            self.ifcModel = ifcopenshell.open(ifcModel)
        
        self.EMPTY_PROPERTIES = EMPTY_PROPERTIES
        self.modelName = modelName or "unknown"
        
        # Dictionary to cache processed entities and track hierarchy
        self.processed_entities = {}
        self.entity_guids = {}  # Map entity id to entityGuid
        self.children_cache = {}  # Cache of children for each entity

    def spf2Json(self):
        """
        Build hierarchical tree structure from IFC file
        
        Returns:
        dict: Tree structure with root project and nested children
        """
        # First pass: collect all GlobalIds
        for entity in self.ifcModel:
            if hasattr(entity, 'GlobalId') and entity.GlobalId:
                self.entity_guids[entity.id()] = expandGuid(entity.GlobalId)
        
        # Find root project
        projects = self.ifcModel.by_type('IfcProject')
        if not projects:
            raise ValueError("No IfcProject found in IFC file")
        
        root_project = projects[0]
        root_uuid = str(uuid.uuid4())
        
        # Build tree starting from root
        tree_root = {
            "name": root_uuid,
            "children": [self.build_tree_node(root_project, f"/{root_uuid}")]
        }
        
        return tree_root

    def build_tree_node(self, entity, path_prefix=""):
        """
        Recursively build tree node for entity
        
        Args:
            entity: ifcopenshell entity instance
            path_prefix: current path prefix (e.g., "/uuid/Project")
        
        Returns:
            dict: Tree node with name, attributes, children
        """
        entity_id = entity.id()
        
        # Skip if already processed
        if entity_id in self.processed_entities:
            return self.processed_entities[entity_id]
        
        # Get entity properties
        entity_type = entity.is_a()
        entity_name = self._get_entity_name(entity, entity_type)
        
        # Create path for this node
        node_path = f"{path_prefix}/{entity_name}" if path_prefix else f"/{entity_name}"
        
        # Extract and process attributes
        attributes = self._extract_attributes(entity, entity_type)
        
        # Get children (spatial decomposition, contained elements, etc.)
        children_nodes = self._get_children_nodes(entity, node_path)
        
        # Build node
        node = {
            "name": node_path,
            "attributes": attributes if attributes else {}
        }
        
        if children_nodes:
            node["children"] = children_nodes
        else:
            node["children"] = []
        
        # Cache the result
        self.processed_entities[entity_id] = node
        
        return node

    def _get_entity_name(self, entity, entity_type):
        """Extract meaningful name for entity path"""
        # Try to get Name attribute
        if hasattr(entity, 'Name') and entity.Name:
            # Sanitize name for path use
            name = str(entity.Name).replace(' ', '_').replace('/', '_')
            return name
        else:
            # Use entity type as fallback
            return entity_type

    def _extract_attributes(self, entity, entity_type):
        """Extract and process entity attributes"""
        attributes = {}
        
        # Get all first-level attributes from __dict__
        entityAttributes = entity.__dict__.copy()
        
        # Convert all attribute keys to toLowerCamelcase
        entityAttributes = {toLowerCamelcase(key): value for key, value in entityAttributes.items()}
        
        # Handle specific entity types
        if entity.is_a('IfcObjectDefinition'):
            if hasattr(entity, 'GlobalId') and entity.GlobalId:
                attributes['entityGuid'] = expandGuid(entity.GlobalId)
            attributes['entityType'] = entity_type
            attributes['componentGuid'] = generateDeterministicGuid(
                self.modelName, 
                entity_type, 
                attributes.get('entityGuid', '')
            )
        
        if entity.is_a('IfcRelationship'):
            if 'globalId' in entityAttributes:
                attributes['componentGuid'] = expandGuid(entityAttributes['globalId'])
            
            # Find the first key starting with 'Relating' and use its value as entityGuid
            relating_keys = sorted([key for key in entityAttributes.keys() if key.startswith('relating')])
            if relating_keys:
                first_relating_key = relating_keys[0]
                relating_value = entityAttributes[first_relating_key]
                if isinstance(relating_value, str):
                    attributes['entityGuid'] = expandGuid(relating_value)
                elif hasattr(relating_value, 'GlobalId'):
                    attributes['entityGuid'] = expandGuid(relating_value.GlobalId)
                else:
                    attributes['entityGuid'] = ""
        
        if entity.is_a('IfcPropertySet'):
            if hasattr(entity, 'GlobalId') and entity.GlobalId:
                attributes['componentGuid'] = expandGuid(entity.GlobalId)
            if hasattr(entity, 'PropertyDefinitionOf') and len(entity.PropertyDefinitionOf) > 0:
                relation = entity.PropertyDefinitionOf[0]
                testentity = relation.RelatedObjects[0]
                if hasattr(testentity, 'GlobalId'):
                    attributes['entityGuid'] = expandGuid(testentity.GlobalId)
        
        # Process remaining attributes
        processed_attrs = self._appendAttributes(entityAttributes, entity_type)
        attributes.update(processed_attrs)
        
        # Handle geometry/representation
        if hasattr(entity, 'Representation') and entity.Representation:
            try:
                obj = self._toObj(entity)
                if obj:
                    entity_guid = attributes.get('entityGuid', expandGuid(entity.GlobalId) if hasattr(entity, 'GlobalId') else '')
                    attributes['representation'] = {
                        'type': 'IfcShapeRepresentation',
                        'format': 'OBJ',
                        'data': obj
                    }
            except Exception as e:
                pass  # Skip if geometry extraction fails
        
        return attributes

    def _appendAttributes(self, currentAttributes, entity_type):
        """Process and format attributes for output"""
        entity_dict = {}
        
        keys = sorted(currentAttributes.keys())
        
        for attr_name in keys:
            # Skip excluded attributes
            if attr_name.lower() in EXCLUDE_ATTRIBUTES:
                continue
            
            # Skip internal attributes
            if attr_name.startswith('_'):
                continue
            
            attr_value = currentAttributes[attr_name]
            
            # Convert to JSON-serializable format
            try:
                json_value = self._getAttributeValue(attr_value)
            except:
                json_value = None
            
            if json_value is None:
                continue
            
            # Expand GUIDs
            if attr_name in EXPAND_GUID_ATTRIBUTES and json_value is not None:
                json_value = expandGuid(json_value)
            
            # Append "Component" to type attributes
            if attr_name == 'type' and json_value is not None:
                json_value = json_value + 'Component'
            
            # Apply substitutions
            if attr_name in ATTRIBUTE_SUBSTITUTIONS:
                display_attr_name = ATTRIBUTE_SUBSTITUTIONS[attr_name]
            else:
                display_attr_name = attr_name
            
            display_attr_name = toLowerCamelcase(display_attr_name)
            
            if display_attr_name not in entity_dict:
                if json_value is not None:
                    entity_dict[display_attr_name] = json_value
                elif INCLUDE_EMPTY_PROPERTIES:
                    entity_dict[display_attr_name] = ""
        
        return entity_dict

    def _getAttributeValue(self, value):
        """Convert attribute values to JSON-serializable format"""
        if value is None:
            return None
        elif isinstance(value, ifcopenshell.entity_instance):
            # For nested entities, return reference instead of recursing
            if hasattr(value, 'GlobalId') and value.GlobalId:
                return {
                    'ref': expandGuid(value.GlobalId),
                    'type': value.is_a()
                }
            return None
        elif isinstance(value, (list, tuple)):
            try:
                return [self._getAttributeValue(v) for v in value]
            except:
                return None
        elif isinstance(value, (str, int, float, bool)):
            return value
        else:
            # Try to convert to string
            try:
                return str(value)
            except:
                return None

    def _get_children_nodes(self, entity, parent_path):
        """Get child entities for spatial/containment hierarchy"""
        children = []
        entity_id = entity.id()
        
        # Check cache
        if entity_id in self.children_cache:
            return self.children_cache[entity_id]
        
        # Get spatial decomposition (IsDecomposedBy)
        if hasattr(entity, 'IsDecomposedBy'):
            for rel in entity.IsDecomposedBy:
                if hasattr(rel, 'RelatedObjects'):
                    for related in rel.RelatedObjects:
                        child_node = self.build_tree_node(related, parent_path)
                        children.append(child_node)
        
        # Get contained elements (Contains)
        if hasattr(entity, 'Contains'):
            for rel in entity.Contains:
                if hasattr(rel, 'RelatedElements'):
                    for related in rel.RelatedElements:
                        child_node = self.build_tree_node(related, parent_path)
                        children.append(child_node)
        
        # Cache result
        self.children_cache[entity_id] = children
        
        return children

    def _toObj(self, entity):
        """Convert IfcProduct to OBJ mesh format"""
        if not hasattr(entity, 'Representation') or not entity.Representation:
            return None
        
        try:
            shape = ifcopenshell.geom.create_shape(self.settings, entity)
            
            if not hasattr(shape.geometry, 'verts') or not hasattr(shape.geometry, 'faces'):
                return None
            
            verts = shape.geometry.verts
            vertsList = [' '.join(map(str, verts[x:x+3]))
                         for x in range(0, len(verts), 3)]
            vertString = 'v ' + '\nv '.join(vertsList) + '\n'
            
            faces = shape.geometry.faces
            facesList = [' '.join(map(str, [f + 1 for f in faces[x:x+3]]))
                         for x in range(0, len(faces), 3)]
            faceString = 'f ' + '\nf '.join(map(str, facesList)) + '\n'
            
            return vertString + faceString
        except Exception as e:
            return None


def main():
    """Main entry point for processing IFC files"""
    parser = argparse.ArgumentParser(
        description='Convert IFC file to hierarchical JSON tree format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ifc4ingestor_hierarchical.py input.ifc
  python ifc4ingestor_hierarchical.py input.ifc -o output.json
  python ifc4ingestor_hierarchical.py input.ifc --empty-properties
  python ifc4ingestor_hierarchical.py input.ifc --model-name "MyProject"
        """
    )
    
    parser.add_argument('input',
                        help='Input IFC file path')
    parser.add_argument('-o', '--output',
                        help='Output JSON file path (if not specified, prints to stdout)')
    parser.add_argument('--empty-properties',
                        action='store_true',
                        help='Include empty properties in output')
    parser.add_argument('--model-name',
                        help='Model name for deterministic GUID generation')
    
    args = parser.parse_args()
    
    # Check if input file exists
    import os
    if not os.path.isfile(args.input):
        print(f"Error: Input file '{args.input}' not found.", file=sys.stderr)
        sys.exit(1)
    
    try:
        # Create converter instance
        converter = IFC2JSONHierarchical(
            args.input,
            EMPTY_PROPERTIES=args.empty_properties,
            modelName=args.model_name
        )
        
        # Convert to hierarchical JSON
        tree_structure = converter.spf2Json()
        
        # Output results
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(tree_structure, f, indent=2, default=str)
            print(f"Successfully wrote hierarchical structure to {args.output}")
        else:
            json_output = json.dumps(tree_structure, indent=2, default=str)
            print(json_output)
            
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
