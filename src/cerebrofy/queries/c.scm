; C captures for Cerebrofy Universal Parser

(function_definition
  declarator: (function_declarator
    declarator: (identifier) @name)) @function.def

(struct_specifier
  name: (type_identifier) @name) @class.def

(preproc_include) @import

(call_expression
  function: (identifier) @name) @call
