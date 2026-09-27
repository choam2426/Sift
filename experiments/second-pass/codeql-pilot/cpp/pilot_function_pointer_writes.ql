import cpp

// Assignments to the Code2 function-pointer field. A write is a possible
// binding source; it does not establish which target a later indirect call uses.
from AssignExpr assignment, FieldAccess field, Expr value, Function enclosing
where
  assignment.getLValue() = field and
  value = assignment.getRValue() and
  field.getTarget().getName() = "Code2" and
  enclosing = assignment.getEnclosingFunction() and
  enclosing.getLocation().getFile().getRelativePath() = "C/XzDec.c"
select
  enclosing.getLocation().getFile().getRelativePath(),
  enclosing.getLocation().getStartLine(),
  enclosing.getName(),
  assignment.getLocation().getStartLine(),
  assignment.getLocation().getStartColumn(),
  assignment.getLocation().getEndLine(),
  assignment.getLocation().getEndColumn(),
  value.getLocation().getStartLine(),
  value.getLocation().getStartColumn(),
  value.getLocation().getEndLine(),
  value.getLocation().getEndColumn()
