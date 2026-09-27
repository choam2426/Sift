import cpp

// Extract declared parameter types for source functions, without security rules.
from Function function, Parameter parameter, int index
where
  parameter = function.getParameter(index) and
  function.getLocation().getFile().getRelativePath().regexpMatch("C/.*")
select
  function.getLocation().getStartLine(),
  function.getName(),
  index,
  parameter.getName(),
  parameter.getType().toString(),
  parameter.getLocation().getFile().getRelativePath(),
  parameter.getLocation().getStartLine()
