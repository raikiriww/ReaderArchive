export function cleanTag(value: string): string {
  return String(value || "").replace(/\s+/g, " ").trim();
}

export function validTagFilters(filters: string[], tags: Array<{ name: string }>): string[] {
  const available = new Map(tags.map((tag) => [tag.name.toLowerCase(), tag.name]));
  const seen = new Set<string>();
  return filters.reduce<string[]>((result, tag) => {
    const name = available.get(tag.toLowerCase());
    if (!name || seen.has(name.toLowerCase())) return result;
    seen.add(name.toLowerCase());
    result.push(name);
    return result;
  }, []);
}
