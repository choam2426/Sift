import cpp

// Enumerate typedef declarations available in the compiled source unit.
from TypedefType type
where type.getLocation().getFile().getRelativePath().regexpMatch("C/.*")
select
  type.getName(),
  type.getLocation().getFile().getRelativePath(),
  type.getLocation().getStartLine(),
  type.getLocation().getStartColumn(),
  type.getLocation().getEndLine(),
  type.getLocation().getEndColumn(),
  type.getBaseType().toString(),
  type.getBaseType().getLocation().getFile().getRelativePath(),
  type.getBaseType().getLocation().getStartLine(),
  type.getBaseType().getLocation().getEndLine()
