import { client } from "@/client/client.gen";
import { ApiError, getAccessToken, redirectToLogin } from "../../api/client";
import type { ArchiveTask } from "../../types/domain";

export interface SearchFilters {
	content_type: "all" | "web" | "video" | "file";
	source: "" | "manual" | "rss";
	date_from: string;
	tags: string[];
	include_read: boolean;
	exact: boolean;
	sort: "relevance" | "newest" | "oldest";
}
export interface SearchMatch {
	excerpt: string;
	score: number;
	kind: "title" | "tag" | "url" | "body" | "semantic";
	highlights: { start: number; end: number }[];
	paragraph_highlights?: { start: number; end: number }[];
	file_name?: string | null;
	paragraph_index?: number | null;
	location_text?: string | null;
	strength?: "strong" | "possible";
	version_count?: number;
	version_task_ids?: string[];
}
export type SearchTask = Omit<ArchiveTask, "search_match"> & {
	search_match?: SearchMatch | null;
};
export interface SearchPage {
	items: SearchTask[];
	total: number;
	limit: number;
	offset: number;
	has_more: boolean;
	mode: "hybrid" | "keyword";
	coverage: {
		total: number;
		ready: number;
		pending: number;
		unavailable: number;
	};
	total_is_exact: boolean;
}
export async function searchArchives(
	query: string,
	filters: SearchFilters,
	offset: number,
	signal?: AbortSignal,
): Promise<SearchPage> {
	const url = client.buildUrl({
		url: "/api/v1/archive-search",
		query: {
			q: query,
			...filters,
			source: filters.source || undefined,
			date_from: filters.date_from
				? new Date(`${filters.date_from}T00:00:00`).toISOString()
				: undefined,
			tags: filters.tags.length ? filters.tags : undefined,
			limit: 20,
			offset,
		},
	});
	const response = await fetchSearchResource(url, {
		signal,
		headers: { Authorization: `Bearer ${getAccessToken()}` },
	});
	if (!response.ok) {
		if (response.status === 401 || response.status === 403) redirectToLogin();
		let message = `搜索暂时不可用（${response.status}）`;
		try {
			const error = await response.json();
			if (typeof error.detail === "string") message = error.detail;
		} catch {
			/* use fallback */
		}
		throw new ApiError(message, response.status);
	}
	return response.json();
}

export interface SearchText {
	title: string;
	paragraphs: string[];
	file_name: string | null;
}
export async function readSearchText(
	taskId: string,
	signal?: AbortSignal,
): Promise<SearchText> {
	const response = await fetchSearchResource(
		client.buildUrl({
			url: "/api/v1/archive-search/{task_id}/text",
			path: { task_id: taskId },
		}),
		{ signal, headers: { Authorization: `Bearer ${getAccessToken()}` } },
	);
	if (!response.ok) {
		if (response.status === 401 || response.status === 403) redirectToLogin();
		throw new ApiError(
			response.status === 404
				? "这篇存档目前没有可阅读的正文。"
				: "暂时无法读取正文，请重试。",
			response.status,
		);
	}
	return response.json();
}

async function fetchSearchResource(url: string, options: RequestInit): Promise<Response> {
  try {
    return await fetch(url, options);
  } catch (error) {
    if (options.signal?.aborted || (error instanceof Error && error.name === "AbortError")) throw error;
    throw new ApiError("无法连接服务器，请检查网络后重试。", 0);
  }
}
