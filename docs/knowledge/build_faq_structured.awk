BEGIN {
  in_q = 0
  ans = ""
  q = ""
  print "# Acomara FAQ - Structured (v1)"
  print ""
  print "## Itinerarios y Programas"
  print ""
  print "- Se conservaron los itinerarios operativos del documento original en el archivo crudo."
  print "- Esta version prioriza formato Pregunta/Respuesta para atencion comercial."
  print ""
}
{
  line = $0
  gsub(/\r/, "", line)
  gsub(/\302\240/, " ", line)
  gsub(/[[:space:]]+$/, "", line)
  gsub(/^[[:space:]]+/, "", line)

  if (line == "") {
    if (in_q && ans != "" && substr(ans, length(ans), 1) != "\n") {
      ans = ans "\n"
    }
    next
  }

  if (line ~ /\?$/) {
    if (in_q) {
      print "### " q
      print ""
      print ans
      print ""
    }
    q = line
    ans = ""
    in_q = 1
    next
  }

  if (in_q) {
    if (line ~ /^[-*•]/) {
      sub(/^[-*•][[:space:]]*/, "", line)
      ans = ans "- " line "\n"
    } else {
      if (ans != "" && substr(ans, length(ans), 1) != "\n") {
        ans = ans " "
      }
      ans = ans line
    }
  }
}
END {
  if (in_q) {
    print "### " q
    print ""
    print ans
    print ""
  }
}
