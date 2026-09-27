import cpp

// Extract source-backed field accesses without assigning security meaning.
private string modificationKind(FieldAccess access) {
  access.isModified() and result = "modified"
  or
  not access.isModified() and result = "not_modified"
}

from FieldAccess access, Field field, Function enclosing
where
  access.getTarget() = field and
  enclosing = access.getEnclosingFunction() and
  access.getFile().getRelativePath() = "C/XzDec.c"
select
  enclosing.getLocation().getFile().getRelativePath(),
  enclosing.getLocation().getStartLine(),
  enclosing.getName(),
  field.getName(),
  field.getLocation().getFile().getRelativePath(),
  field.getLocation().getStartLine(),
  access.getLocation().getStartLine(),
  access.getLocation().getStartColumn(),
  access.getLocation().getEndLine(),
  access.getLocation().getEndColumn(),
  access.getQualifier().toString(),
  access.toString(),
  modificationKind(access)
