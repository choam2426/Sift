import cpp

private string modificationKind(VariableAccess access) {
  access.isModified() and result = "modified"
  or
  not access.isModified() and result = "not_modified"
}

// Source locations where a named parameter is accessed. This is a syntactic
// fact and does not establish a value path through the enclosing function.
from Function enclosing, Parameter parameter, int index, VariableAccess access
where
  parameter = enclosing.getParameter(index) and
  access.getTarget() = parameter and
  access.getEnclosingFunction() = enclosing and
  enclosing.getLocation().getFile().getRelativePath().regexpMatch("C/.*") and
  access.getLocation().getFile().getRelativePath().regexpMatch("C/.*")
select
  enclosing.getLocation().getFile().getRelativePath(),
  enclosing.getLocation().getStartLine(),
  enclosing.getName(),
  index,
  parameter.getName(),
  access.getLocation().getStartLine(),
  access.getLocation().getStartColumn(),
  access.getLocation().getEndLine(),
  access.getLocation().getEndColumn(),
  modificationKind(access)
