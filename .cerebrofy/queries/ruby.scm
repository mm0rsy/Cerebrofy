; Ruby captures for Cerebrofy Universal Parser

(method
  name: (identifier) @name) @function.def

(singleton_method
  name: (identifier) @name) @function.def

(class
  name: (constant) @name) @class.def

(module
  name: (constant) @name) @class.def

(call
  method: (identifier) @name) @call
