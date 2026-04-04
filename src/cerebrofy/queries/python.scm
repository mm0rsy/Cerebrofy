; Python captures for Cerebrofy Universal Parser

(function_definition
  name: (identifier) @name) @function.def

(class_definition
  name: (identifier) @name) @class.def

(import_statement) @import

(import_from_statement) @import

(call
  function: (_) @name) @call
