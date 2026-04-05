; Java captures for Cerebrofy Universal Parser

(method_declaration
  name: (identifier) @name) @function.def

(class_declaration
  name: (identifier) @name) @class.def

(interface_declaration
  name: (identifier) @name) @class.def

(import_declaration) @import

(method_invocation
  name: (identifier) @name) @call
