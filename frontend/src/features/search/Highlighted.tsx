import type { SearchMatch } from "./api";

export function Highlighted({
	match,
	fallback,
}: {
	match?: SearchMatch | null;
	fallback: string;
}): JSX.Element {
	if (!match?.excerpt) return <>{fallback}</>;
	const text = Array.from(match.excerpt);
	const spans = (match.highlights || [])
		.filter(
			(span) =>
				span.start >= 0 && span.end > span.start && span.end <= text.length,
		)
		.sort((a, b) => a.start - b.start);
	const parts: React.ReactNode[] = [];
	let start = 0;
	for (const span of spans) {
		if (span.start < start) continue;
		parts.push(
			text.slice(start, span.start).join(""),
			<mark tabIndex={-1} key={`${span.start}-${span.end}`}>
				{text.slice(span.start, span.end).join("")}
			</mark>,
		);
		start = span.end;
	}
	parts.push(text.slice(start).join(""));
	return <>{parts}</>;
}
