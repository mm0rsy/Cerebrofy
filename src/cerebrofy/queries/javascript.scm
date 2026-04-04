; JavaScript captures for Cerebrofy Universal Parser
; Arrow functions without names are intentionally excluded.

(function_declaration
  name: (identifier) @name) @function.def

(function_expression
  name: (identifier) @name) @function.def

(class_declaration
  name: (identifier) @name) @class.def

(import_declaration) @import

(call_expression
  function: (_) @name) @call
