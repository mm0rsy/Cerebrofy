; C header captures for Cerebrofy Universal Parser
; Headers contain declarations, not definitions.

(declaration
  declarator: (function_declarator
    declarator: (identifier) @name)) @function.def

(struct_specifier
  name: (type_identifier) @name) @class.def

(preproc_include) @import
