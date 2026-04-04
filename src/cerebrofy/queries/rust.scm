; Rust captures for Cerebrofy Universal Parser

(function_item
  name: (identifier) @name) @function.def

(impl_item
  type: (_) @name) @class.def

(struct_item
  name: (type_identifier) @name) @class.def

(enum_item
  name: (type_identifier) @name) @class.def

(use_declaration) @import

(call_expression
  function: (_) @name) @call
