import cpp

from Function function
where function.hasDefinition()
select
  function.getLocation().getFile().getRelativePath(),
  function.getLocation().getStartLine(),
  function.getName()
