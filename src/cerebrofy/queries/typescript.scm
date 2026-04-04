; TypeScript captures for Cerebrofy Universal Parser
; Arrow functions without names are intentionally excluded.

(function_declaration
  name: (identifier) @name) @function.def

(function_expression
  name: (identifier) @name) @function.def

(method_definition
  name: (property_identifier) @name) @function.def

(class_declaration
  name: (type_identifier) @name) @class.def

(type_alias_declaration
  name: (type_identifier) @name) @class.def

(interface_declaration
  name: (type_identifier) @name) @class.def

(import_declaration) @import

(call_expression
  function: (_) @name) @call
