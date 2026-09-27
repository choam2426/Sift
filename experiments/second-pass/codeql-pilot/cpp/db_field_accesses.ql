import cpp

private string modificationKind(FieldAccess access) {
  access.isModified() and result = "modified"
  or
  not access.isModified() and result = "not_modified"
}

// Field access locations and declaration identity, without object-alias claims.
from FieldAccess access, Field field, Function enclosing
where
  access.getTarget() = field and
  enclosing = access.getEnclosingFunction() and
  enclosing.getLocation().getFile().getRelativePath().regexpMatch("C/.*")
select
  enclosing.getLocation().getFile().getRelativePath(),
  enclosing.getLocation().getStartLine(),
  enclosing.getName(),
  field.getName(),
  field.getLocation().getFile().getRelativePath(),
  field.getLocation().getStartLine(),
  access.getLocation().getFile().getRelativePath(),
  access.getLocation().getStartLine(),
  access.getLocation().getStartColumn(),
  access.getLocation().getEndLine(),
  access.getLocation().getEndColumn(),
  access.getQualifier().toString(),
  modificationKind(access)
