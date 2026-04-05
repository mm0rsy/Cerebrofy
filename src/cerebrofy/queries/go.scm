; Go captures for Cerebrofy Universal Parser

(function_declaration
  name: (identifier) @name) @function.def

(method_declaration
  name: (field_identifier) @name) @function.def

(type_declaration
  (type_spec
    name: (type_identifier) @name)) @class.def

(import_declaration) @import

(call_expression
  function: (_) @name) @call
