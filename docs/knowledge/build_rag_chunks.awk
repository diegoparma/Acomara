BEGIN {
  q = ""
  a = ""
  id = 0
}

function trim(s) {
  gsub(/^[ \t\r\n]+/, "", s)
  gsub(/[ \t\r\n]+$/, "", s)
  return s
}

function escape_json(s, t) {
  t = s
  gsub(/\\/, "\\\\", t)
  gsub(/"/, "\\\"", t)
  gsub(/\r/, "", t)
  gsub(/\t/, " ", t)
  gsub(/\n+/, "\\n", t)
  return t
}

function topic_from_question(question, lower) {
  lower = tolower(question)
  if (lower ~ /price|cheaper|cost|permit/) return "pricing"
  if (lower ~ /route|normal|polish|itinerar|distance|days|hike/) return "itinerary"
  if (lower ~ /included|not included|optional/) return "services"
  if (lower ~ /gear|boots|crampon|backpack|ice axe|camelbak/) return "equipment"
  if (lower ~ /guide|group size|porters|tip/) return "guides_and_porters"
  if (lower ~ /fly|airport|hotel|luggage|communication/) return "logistics"
  if (lower ~ /insurance|passport|visa|age/) return "requirements"
  if (lower ~ /training|nutrition|hydration|diamox/) return "preparation"
  if (lower ~ /abandon|descend|rescue/) return "risk_and_policies"
  return "general"
}

function flush_record() {
  if (q == "") return
  id++
  qq = escape_json(trim(q))
  aa = escape_json(trim(a))
  topic = topic_from_question(q)
  printf "{\"id\":\"faq-%03d\",\"topic\":\"%s\",\"question\":\"%s\",\"answer\":\"%s\",\"source\":\"faq_structured.md\"}\n", id, topic, qq, aa
  q = ""
  a = ""
}

/^### / {
  flush_record()
  q = substr($0, 5)
  next
}

{
  if (q != "") {
    line = $0
    gsub(/\r/, "", line)
    if (a == "") a = line
    else a = a "\n" line
  }
}

END {
  flush_record()
}
