import { z } from "zod";
import type { SearchFilters } from "./api";
export const searchDefaults: SearchFilters = {
	content_type: "all",
	source: "",
	date_from: "",
	tags: [],
	include_read: true,
	exact: false,
	sort: "relevance",
};
const stateSchema = z.object({
	query: z.string().max(240).default(""),
	filters: z
		.object({
			content_type: z.enum(["all", "web", "video", "file"]).default("all"),
			source: z.enum(["", "manual", "rss"]).default(""),
			date_from: z
				.string()
				.refine(
					(value) =>
						!value ||
						(/^\d{4}-\d{2}-\d{2}$/.test(value) &&
							!Number.isNaN(new Date(`${value}T00:00:00Z`).getTime()) &&
							new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) ===
								value),
				)
				.catch("")
				.default(""),
			tags: z.array(z.string()).max(50).default([]),
			include_read: z.boolean().default(true),
			exact: z.boolean().default(false),
			sort: z.enum(["relevance", "newest", "oldest"]).default("relevance"),
		})
		.default(searchDefaults),
	offset: z.number().int().nonnegative().default(0),
	selectedId: z.string().nullable().default(null),
	reading: z.boolean().default(false),
});
export type SearchLocationState = z.infer<typeof stateSchema>;
export function readSearchLocation(href: string = window.location.href): SearchLocationState {
	try {
		const state = stateSchema.parse(
			JSON.parse(
				new URL(href).searchParams.get("reader_search") || "{}",
			),
		);
		return { ...state, reading: state.reading && Boolean(state.query.trim() && state.selectedId) };
	} catch {
		return stateSchema.parse({});
	}
}
export function writeSearchLocation(
	state: SearchLocationState,
	push = false,
): void {
	const url = new URL(window.location.href);
	url.searchParams.set("reader_search", JSON.stringify(state));
	if (url.href !== window.location.href)
		window.history[push ? "pushState" : "replaceState"](
			{ ...window.history.state },
			"",
			url,
		);
}
