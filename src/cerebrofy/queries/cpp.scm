; C++ captures for Cerebrofy Universal Parser

(function_definition
  declarator: (function_declarator
    declarator: (identifier) @name)) @function.def

(function_definition
  declarator: (reference_declarator
    (function_declarator
      declarator: (identifier) @name))) @function.def

(class_specifier
  name: (type_identifier) @name) @class.def

(struct_specifier
  name: (type_identifier) @name) @class.def

(namespace_definition
  name: (namespace_identifier) @name) @class.def

(preproc_include) @import

(call_expression
  function: (_) @name) @call
