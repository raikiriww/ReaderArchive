import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import {
	Archive,
	ArrowLeft,
	ArrowUpRight,
	Check,
	ChevronLeft,
	ChevronRight,
	Clock,
	FileText,
	Search,
	SlidersHorizontal,
	X,
} from "lucide-react";
import type { ArchiveTag } from "../../types/domain";
import {
	formatDate,
	safeUrl,
	sourceLabel,
	taskTitle,
} from "../../utils/format";
import { SavedVersions } from "./SavedVersions";
import { Highlighted } from "./Highlighted";
import {
	readSearchText,
	searchArchives,
	type SearchFilters,
	type SearchMatch,
	type SearchTask,
} from "./api";

import {
	readSearchLocation,
	writeSearchLocation,
	searchDefaults as defaults,
} from "./state";
const matchLabels: Record<SearchMatch["kind"], string> = {
	title: "标题命中",
	tag: "标签命中",
	url: "网址命中",
	body: "正文命中",
	semantic: "相关内容",
};
const recentKey = "reader-search-recent";
function loadRecent(): string[] {
	try {
		const value = JSON.parse(sessionStorage.getItem(recentKey) || "[]");
		return Array.isArray(value)
			? value
					.filter((item): item is string => typeof item === "string")
					.slice(0, 6)
			: [];
	} catch {
		return [];
	}
}

export function SearchWorkspace({
	open,
	focusRequest,
	tags,
	onClose,
	onMarkRead,
}: {
	open: boolean;
	focusRequest: number;
	tags: ArchiveTag[];
	onClose: () => void;
	onMarkRead: (id: string) => Promise<void>;
}): JSX.Element {
	const [initial] = useState(readSearchLocation);
	const [restoreSelectionId, setRestoreSelectionId] = useState(
		initial.selectedId,
	);
	const [draft, setDraft] = useState(initial.query);
	const [query, setQuery] = useState(initial.query);
	const [filters, setFilters] = useState<SearchFilters>(initial.filters);
	const [offset, setOffset] = useState(initial.offset);
	const [selected, setSelected] = useState<SearchTask | null>(null);
	const [showPossible, setShowPossible] = useState(false);
	const [filtersOpen, setFiltersOpen] = useState(false);
	const [suggestionsOpen, setSuggestionsOpen] = useState(false);
	const [recent, setRecent] = useState(loadRecent);
	const [reading, setReading] = useState(initial.reading);
	const input = useRef<HTMLInputElement>(null);
	const lastFocusRequest = useRef(0);
	const list = useRef<HTMLDivElement>(null);
	const resultButton = useRef<HTMLButtonElement | null>(null);
	const previewClose = useRef<HTMLButtonElement>(null);
	const readButton = useRef<HTMLButtonElement>(null);
	const search = useQuery({
		queryKey: ["archive-search", query, filters, offset],
		queryFn: ({ signal }) => searchArchives(query, filters, offset, signal),
		enabled: open && Boolean(query),
		staleTime: 30000,
	});
	const data = search.data;
	const items = data?.items ?? [];
	const possibleCount = items.filter(
		(item) => item.search_match?.strength === "possible",
	).length;
	const strongCount = items.length - possibleCount;
	// Preserve the server's leading results even when their match is semantic.
	const firstDirectIndex = items.findIndex(
		(item) => item.search_match?.strength !== "possible",
	);
	const collapsibleCount = items.filter(
		(item, index) => item.search_match?.strength === "possible" && firstDirectIndex >= 0 && index > firstDirectIndex,
	).length;
	const active =
		items.find((item) => item.task_id === selected?.task_id) ?? selected;
	const showingReader = reading && Boolean(active);
	const text = useQuery({
		queryKey: ["archive-search-text", active?.task_id],
		queryFn: ({ signal }) => readSearchText(active?.task_id ?? "", signal),
		enabled: open && reading && Boolean(active),
		staleTime: 30000,
	});
	const filterCount =
		Number(filters.content_type !== "all") +
		Number(Boolean(filters.source)) +
		Number(Boolean(filters.date_from)) +
		filters.tags.length +
		Number(!filters.include_read) +
		Number(filters.exact);

	useEffect(() => {
		const restore = () => {
			const state = readSearchLocation();
			setDraft(state.query);
			setQuery(state.query);
			setFilters((current) =>
				JSON.stringify(current) === JSON.stringify(state.filters)
					? current
					: state.filters,
			);
			setOffset(state.offset);
			setReading(state.reading);
			setRestoreSelectionId(state.selectedId);
			setSelected((current) =>
				current?.task_id === state.selectedId ? current : null,
			);
			setSuggestionsOpen(false);
		};
		window.addEventListener("popstate", restore);
		return () => window.removeEventListener("popstate", restore);
	}, []);
	useEffect(() => {
		if (open)
			writeSearchLocation({
				query,
				filters,
				offset,
				selectedId: selected?.task_id ?? restoreSelectionId,
				reading,
			});
	}, [
		open,
		query,
		filters,
		offset,
		selected?.task_id,
		restoreSelectionId,
		reading,
	]);
	useEffect(() => {
		if (data && offset > 0 && offset >= data.total) {
			setOffset(data.total > 0 ? Math.floor((data.total - 1) / data.limit) * data.limit : 0);
			setSelected(null);
			setReading(false);
		}
	}, [data, offset]);
	useEffect(() => {
		if (data && restoreSelectionId) {
			const restored = data.items.find(
				(item) => item.task_id === restoreSelectionId,
			);
			setSelected(restored ?? null);
            if (restored?.search_match?.strength === "possible") setShowPossible(true);
			setRestoreSelectionId(null);
			if (!restored) setReading(false);
		}
	}, [data, restoreSelectionId]);
	useEffect(() => {
		if (open && focusRequest > lastFocusRequest.current) {
			lastFocusRequest.current = focusRequest;
			setReading(false);
			if (window.matchMedia("(max-width: 760px)").matches) setSelected(null);
			requestAnimationFrame(() => {
				input.current?.focus();
				input.current?.select();
			});
			setSuggestionsOpen(true);
		}
	}, [open, focusRequest]);
	// These values identify a new result set; scrolling is intentionally reset only for that change.
	// biome-ignore lint/correctness/useExhaustiveDependencies: the dependencies are the result-set identity.
	useEffect(() => {
		list.current?.scrollTo(0, 0);
	}, [query, filters, offset]);
	useEffect(() => {
		if (
			data &&
			selected &&
			!data.items.some((item) => item.task_id === selected.task_id)
		) {
			setSelected(null);
			setReading(false);
		}
	}, [data, selected]);
	useEffect(() => {
		if (open && selected && window.matchMedia("(max-width: 760px)").matches)
			previewClose.current?.focus();
	}, [selected, open]);
	useEffect(() => {
		if (reading && text.data)
			requestAnimationFrame(() => {
				const match = document.getElementById(
					`search-paragraph-${active?.search_match?.paragraph_index}`,
				);
				const target =
					match?.querySelector("mark") ??
					match ??
					document.getElementById("search-reader-title");
				target?.scrollIntoView({ block: "center" });
				if (target instanceof HTMLElement)
					target.focus({ preventScroll: true });
			});
	}, [reading, text.data, active?.search_match?.paragraph_index]);
	function startReading() {
		writeSearchLocation(
			{
				query,
				filters,
				offset,
				selectedId: active?.task_id ?? null,
				reading: true,
			},
			true,
		);
		setReading(true);
	}
	function returnToResults() {
		setReading(false);
		requestAnimationFrame(() => readButton.current?.focus());
	}
	function closePreview() {
		setSelected(null);
		setReading(false);
		requestAnimationFrame(() => resultButton.current?.focus());
	}
	function execute(value: string) {
		const next = value.trim();
		if (!next) return;
		if (next === query && offset === 0) void search.refetch();
		setRestoreSelectionId(null);
		setShowPossible(false);
		setDraft(next);
		setQuery(next);
		setOffset(0);
		setSelected(null);
		setReading(false);
		setSuggestionsOpen(false);
		const updated = [next, ...recent.filter((item) => item !== next)].slice(
			0,
			6,
		);
		setRecent(updated);
		try {
			sessionStorage.setItem(recentKey, JSON.stringify(updated));
		} catch {
			/* browsing remains available without storage */
		}
	}
	function changeFilter(next: Partial<SearchFilters>) {
		setRestoreSelectionId(null);
		setShowPossible(false);
		setFilters((current) => ({ ...current, ...next }));
		setOffset(0);
		setSelected(null);
	}
	function submit(event: FormEvent) {
		event.preventDefault();
		execute(draft);
	}
	function clearFilters() {
		setRestoreSelectionId(null);
		setShowPossible(false);
		setReading(false);
		setFilters(defaults);
		setOffset(0);
		setSelected(null);
	}

	return (
		<section
			className="archive-search-screen"
			hidden={!open}
			aria-label="搜索存档"
			onKeyDown={(event) => {
				if (event.key === "Escape") {
					if (suggestionsOpen) setSuggestionsOpen(false);
					else if (reading) returnToResults();
					else if (selected) closePreview();
					else onClose();
				}
			}}
		>
			<header className="archive-search-heading" hidden={showingReader}>
				<div className="archive-search-title">
					<button className="text-button" type="button" onClick={onClose}>
						<ArrowLeft size={16} />
						返回存档
					</button>
					<h1>{query ? "搜索结果" : "搜索存档"}</h1>
					<div
						className="archive-search-box"
						role="group"
						onBlur={(event) => {
							if (!event.currentTarget.contains(event.relatedTarget as Node))
								setSuggestionsOpen(false);
						}}
					>
						<form onSubmit={submit} role="search">
							<Search size={18} aria-hidden="true" />
							<input
								id="archiveSearchInput"
								maxLength={240}
								ref={input}
								type="search"
								aria-label="搜索标题、正文或大意"
								placeholder="搜标题、正文，或描述你想找的内容"
								value={draft}
								onFocus={() => setSuggestionsOpen(true)}
								onChange={(event) => {
									setDraft(event.target.value);
									setSuggestionsOpen(true);
								}}
							/>
							{draft && (
								<button
									className="search-icon-button"
									type="button"
									aria-label="清空搜索输入"
									onClick={() => {
										setDraft("");
										input.current?.focus();
									}}
								>
									<X size={16} />
								</button>
							)}
							<button
								className="search-primary"
								type="submit"
								disabled={!draft.trim()}
							>
								搜索
							</button>
						</form>
						{suggestionsOpen && recent.length > 0 && (
							<div className="archive-search-suggestions">
								<div>
									<span>最近搜索</span>
									<button
										className="text-button"
										type="button"
										onClick={() => {
											setRecent([]);
											try {
												sessionStorage.removeItem(recentKey);
											} catch {
												/* no persistence */
											}
										}}
									>
										清空
									</button>
								</div>
								{recent
									.filter((value) => !draft || value.includes(draft))
									.map((value) => (
										<button
											type="button"
											key={value}
											onClick={() => execute(value)}
										>
											<Clock size={15} />
											<span>{value}</span>
											<ArrowUpRight size={14} />
										</button>
									))}
							</div>
						)}
					</div>
				</div>
				<p className="archive-search-scope">
					在全部存档中查找，包含已读内容。筛选后仅搜索指定范围。
				</p>
				<div className="archive-search-filter-line">
					<div
						className="archive-search-types"
						role="group"
						aria-label="内容类型"
					>
						{(
							[
								["all", "全部"],
								["web", "网页"],
								["video", "视频"],
								["file", "文件"],
							] as const
						).map(([value, label]) => (
							<button
								type="button"
								key={value}
								className={filters.content_type === value ? "active" : ""}
								aria-pressed={filters.content_type === value}
								onClick={() => changeFilter({ content_type: value })}
							>
								{label}
							</button>
						))}
					</div>
					<button
						className={`search-secondary ${filtersOpen ? "active" : ""}`}
						type="button"
						aria-expanded={filtersOpen}
						onClick={() => setFiltersOpen((value) => !value)}
					>
						<SlidersHorizontal size={15} />
						筛选{filterCount > 0 && <span>{filterCount}</span>}
					</button>
					<label className="archive-search-check">
						<input
							type="checkbox"
							checked={filters.exact}
							onChange={(event) =>
								changeFilter({ exact: event.target.checked })
							}
						/>
						只匹配原词
					</label>
					<label className="archive-search-sort">
						排序
						<select
							aria-label="搜索结果排序"
							value={filters.sort}
							onChange={(event) =>
								changeFilter({
									sort: event.target.value as SearchFilters["sort"],
								})
							}
						>
							<option value="relevance">最相关</option>
							<option value="newest">最新保存</option>
							<option value="oldest">最早保存</option>
						</select>
					</label>
				</div>
				{filtersOpen && (
					<div className="archive-search-filters">
						<label>
							来源
							<select
								value={filters.source}
								onChange={(event) =>
									changeFilter({
										source: event.target.value as SearchFilters["source"],
									})
								}
							>
								<option value="">全部来源</option>
								<option value="manual">手动保存</option>
								<option value="rss">RSS 订阅</option>
							</select>
						</label>
						<label>
							保存日期
							<input
								type="date"
								aria-label="从哪天开始保存"
								value={filters.date_from}
								onChange={(event) =>
									changeFilter({ date_from: event.target.value })
								}
							/>
						</label>
						<label>
							标签
							<select
								aria-label="按标签筛选"
								value={filters.tags[0] || ""}
								onChange={(event) =>
									changeFilter({
										tags: event.target.value ? [event.target.value] : [],
									})
								}
							>
								<option value="">全部标签</option>
								{tags.map((tag) => (
									<option key={tag.name}>{tag.name}</option>
								))}
							</select>
						</label>
						<label className="archive-search-check">
							<input
								type="checkbox"
								checked={!filters.include_read}
								onChange={(event) =>
									changeFilter({ include_read: !event.target.checked })
								}
							/>
							仅未读
						</label>
					</div>
				)}
				{filterCount > 0 && (
					<div className="archive-search-chips">
						{filters.content_type !== "all" && (
							<span>
								类型：
								{
									{ web: "网页", video: "视频", file: "文件" }[
										filters.content_type
									]
								}
							</span>
						)}
						{filters.source && (
							<span>{filters.source === "rss" ? "RSS 订阅" : "手动保存"}</span>
						)}
						{filters.date_from && <span>{filters.date_from} 起</span>}
						{filters.tags.map((tag) => (
							<span key={tag}>{tag}</span>
						))}
						{!filters.include_read && <span>仅未读</span>}
						{filters.exact && <span>只匹配原词</span>}
						<button type="button" onClick={clearFilters}>
							清除筛选
						</button>
					</div>
				)}
			</header>
			{!query ? (
				<div className="archive-search-welcome">
					<Search size={34} strokeWidth={1.4} />
					<h2>查找你保存过的内容</h2>
					<p>
						记得标题，就输入标题。
						<br />
						只记得内容，也可以用一句话描述。
					</p>
					{recent.length > 0 && (
						<div className="archive-search-recent">
							{recent.map((value) => (
								<button
									className="search-secondary"
									type="button"
									key={value}
									onClick={() => execute(value)}
								>
									<Clock size={15} />
									{value}
									<ArrowUpRight size={15} />
								</button>
							))}
						</div>
					)}
					<small>最近搜索仅保留在当前浏览会话中，可随时清空。</small>
				</div>
			) : (
				<>
					{data && !showingReader && (
						<div className="archive-search-notice" role="status">
							{filters.exact
								? "正在按原词查找。"
								: data.mode === "keyword"
									? "当前按关键词查找，按大意查找暂不可用。"
									: "结合关键词和内容大意查找。"}
							{data.coverage?.pending > 0 && (
								<span>
									{data.coverage.pending} 篇正文正在准备，结果会陆续补齐。
									<button
										className="text-button"
										type="button"
										onClick={() => void search.refetch()}
									>
										刷新
									</button>
								</span>
							)}
							{data.coverage?.unavailable > 0 && (
								<span>
									{data.coverage.unavailable}{" "}
									篇暂无可搜索正文，仍可按标题、标签和网址查找。
								</span>
							)}
						</div>
					)}
					<div
						className={`archive-search-workspace ${active ? "has-selection" : ""}`}
						hidden={showingReader}
					>
						<section
							className="archive-search-results"
							aria-label="搜索结果列表"
						>
							<div className="archive-search-status" aria-live="polite">
								{search.isFetching ? (
									"正在查找…"
								) : search.isError ? (
									"搜索未完成"
								) : (
									<>
										<strong>{data?.total ?? 0}</strong> 条
										{data?.total_is_exact === false ? "候选" : "匹配"}结果
										<span>“{query}”</span>
									</>
								)}
							</div>
							<div className="archive-search-list" ref={list}>
								{!search.isPending && !search.isError && possibleCount > 0 && (
									<div className="archive-search-possible-note">
										{strongCount > 0 ? (
											<>
												<span>
													本页有 {strongCount} 条直接匹配，另有 {possibleCount}{" "}
													条意思可能相关。
												</span>
												{collapsibleCount > 0 && <button
													className="text-button"
													type="button"
													aria-expanded={showPossible}
													onClick={() => setShowPossible((value) => !value)}
												>
													{showPossible ? "收起其余可能相关" : `展开其余 ${collapsibleCount} 条可能相关`}
												</button>}
											</>
										) : (
											<span>这些内容的意思可能相关，请结合原句判断。</span>
										)}
									</div>
								)}
								{search.isPending ? (
									<div className="archive-search-empty">
										<Search size={28} />
										<h2>正在查找存档</h2>
										<p>稍等片刻。</p>
									</div>
								) : search.isError ? (
									<div className="archive-search-empty">
										<h2>暂时没能完成搜索</h2>
										<p>
											{search.error instanceof Error
												? search.error.message
												: "请稍后重试。"}
										</p>
										<button
											className="search-secondary"
											type="button"
											onClick={() => void search.refetch()}
										>
											重新搜索
										</button>
									</div>
								) : items.length === 0 ? (
									<div className="archive-search-empty">
										<Search size={30} />
										<h2>没有找到匹配内容</h2>
										<p>
											{filterCount
												? "可以去掉筛选条件，扩大查找范围。"
												: "试试更短的关键词、文章标题，或换一种描述。"}
										</p>
										{filterCount > 0 && (
											<button
												className="search-secondary"
												type="button"
												onClick={clearFilters}
											>
												清除筛选，重新查找
											</button>
										)}
									</div>
								) : (
									items.map((task, resultIndex) => (
										<article
											className={`archive-search-result ${active?.task_id === task.task_id ? "selected" : ""}`}
											hidden={
												task.search_match?.strength === "possible" &&
												firstDirectIndex >= 0 &&
												resultIndex > firstDirectIndex &&
												!showPossible
											}
											key={task.task_id}
										>
											<button
												type="button"
												aria-pressed={active?.task_id === task.task_id}
												onClick={(event) => {
													resultButton.current = event.currentTarget;
													setSelected(task);
													setReading(false);
													setSuggestionsOpen(false);
												}}
											>
												<span className="archive-search-kind">
													<FileText size={14} />
													{safeUrl(task.url)?.hostname || sourceLabel(task)}
													{!task.is_read && (
														<span className="search-unread">未读</span>
													)}
													<time>{formatDate(task.created_at)}</time>
												</span>
												<h2>{taskTitle(task)}</h2>
												<span className="archive-search-match-label">
													{task.search_match?.strength === "possible"
														? "意思可能相关"
														: task.search_match
															? matchLabels[task.search_match.kind] ||
																"匹配内容"
															: "匹配内容"}
												</span>
												<p className="archive-search-excerpt">
													<Highlighted
														match={task.search_match}
														fallback={task.url}
													/>
												</p>
												<span className="archive-search-result-foot">
													<span className="task-tags">
														{task.tags.slice(0, 3).map((tag) => (
															<span className="tag-chip" key={tag}>
																{tag}
															</span>
														))}
													</span>
													<span>
														{(task.search_match?.version_count ?? 1) > 1 &&
															`${task.search_match?.version_count} 个保存版本 · `}
														查看匹配内容 →
													</span>
												</span>
											</button>
										</article>
									))
								)}
							</div>
							{data && data.total > data.limit && (
								<nav
									className="archive-search-pagination"
									aria-label="搜索结果分页"
								>
									<span>
										{offset + 1}–{Math.min(offset + items.length, data.total)} /{" "}
										{data.total}
									</span>
									<button
										className="search-secondary"
										disabled={offset === 0 || search.isFetching}
										type="button"
										onClick={() => {
											setOffset((value) => Math.max(0, value - 20));
											setSelected(null);
										}}
									>
										<ChevronLeft size={15} />
										上一页
									</button>
									<button
										className="search-secondary"
										disabled={!data.has_more || search.isFetching}
										type="button"
										onClick={() => {
											setOffset((value) => value + 20);
											setSelected(null);
										}}
									>
										下一页
										<ChevronRight size={15} />
									</button>
								</nav>
							)}
						</section>
						<aside
							className={`archive-search-preview ${active ? "open" : ""}`}
							aria-label="匹配内容预览"
						>
							{active ? (
								<>
									<div className="archive-search-preview-header">
										<span>
											<FileText size={16} />
											匹配内容
										</span>
										<button
											ref={previewClose}
											className="search-icon-button"
											type="button"
											aria-label="关闭预览，返回搜索结果"
											onClick={closePreview}
										>
											<X size={19} />
										</button>
									</div>
									<div className="archive-search-preview-body">
										<div className="archive-search-kind">
											{sourceLabel(active)} · {formatDate(active.created_at)}
										</div>
										<h2>{taskTitle(active)}</h2>
										<a
											className="detail-url"
											href={active.url}
											target="_blank"
											rel="noopener noreferrer"
										>
											{active.url}
										</a>
										<div className="archive-search-preview-actions">
											{(active.search_match?.file_name ||
												active.search_match?.kind === "body" ||
												active.search_match?.kind === "semantic") && (
												<button
													ref={readButton}
													className="search-primary"
													type="button"
													onClick={startReading}
												>
													阅读正文
												</button>
											)}
											{active.result?.view_url && (
												<a
													className="search-primary"
													href={active.result.view_url}
													target="_blank"
													rel="noopener noreferrer"
												>
													打开存档
													<ArrowUpRight size={15} />
												</a>
											)}
											<a
												className="search-secondary"
												href={active.url}
												target="_blank"
												rel="noopener noreferrer"
											>
												访问原网页
												<ArrowUpRight size={15} />
											</a>
											{!active.is_read && (
												<button
													className="search-secondary"
													type="button"
													onClick={async () => {
														await onMarkRead(active.task_id);
														await search.refetch();
													}}
												>
													<Check size={15} />
													标为已读
												</button>
											)}
										</div>
										<section className="archive-search-match-section">
											<h3>
												{active.search_match?.strength === "possible"
													? "意思可能相关"
													: active.search_match
														? matchLabels[active.search_match.kind] ||
															"匹配内容"
														: "匹配内容"}
											</h3>
											{active.search_match?.location_text && (
												<p className="archive-search-location">
													{active.search_match.location_text}
												</p>
											)}
											<blockquote>
												<Highlighted
													match={active.search_match}
													fallback={active.url}
												/>
											</blockquote>
										</section>
										{active.tags.length > 0 && (
											<div className="task-tags">
												{active.tags.map((tag) => (
													<span className="tag-chip" key={tag}>
														{tag}
													</span>
												))}
											</div>
										)}
										{(active.search_match?.version_count ?? 1) > 1 &&
										active.search_match?.version_task_ids?.length ? (
											<SavedVersions
												key={active.task_id}
												ids={active.search_match.version_task_ids}
												count={active.search_match.version_count ?? 1}
											/>
										) : null}
										<p className="archive-search-footnote">
											打开存档会在新标签页显示，返回这里可继续查看当前搜索结果。
										</p>
										{!active.result?.view_url && (
											<p className="archive-search-footnote">
												此记录暂没有可打开的网页存档，可访问原网页。
											</p>
										)}
									</div>
								</>
							) : (
								<div className="archive-search-empty">
									<Archive size={32} strokeWidth={1.5} />
									<h2>先看看是否是你要找的</h2>
									<p>选择左侧结果，查看匹配原句和来源，再打开存档阅读。</p>
								</div>
							)}
						</aside>
					</div>
					{reading && active && (
						<section className="archive-search-reader" aria-label="存档正文">
							<div className="archive-search-reader-toolbar">
								<button
									className="search-secondary"
									type="button"
									onClick={returnToResults}
								>
									<ArrowLeft size={16} />
									返回搜索结果
								</button>
								<span>{taskTitle(active)}</span>
								{active.result?.view_url && (
									<a
										className="search-secondary"
										href={active.result.view_url}
										target="_blank"
										rel="noopener noreferrer"
									>
										打开原始存档
										<ArrowUpRight size={15} />
									</a>
								)}
							</div>
							{text.isPending ? (
								<div className="archive-search-empty">
									<p>正在读取正文…</p>
								</div>
							) : text.isError ? (
								<div className="archive-search-empty">
									<h2>暂时无法阅读正文</h2>
									<p>{text.error.message}</p>
									<button
										className="search-secondary"
										type="button"
										onClick={() => void text.refetch()}
									>
										重试
									</button>
								</div>
							) : (
								<article className="archive-search-reading-article">
									<div className="archive-search-kind">
										{sourceLabel(active)} · {formatDate(active.created_at)}
									</div>
									<h1 id="search-reader-title" tabIndex={-1}>
										{text.data?.title || taskTitle(active)}
									</h1>
									<p className="archive-search-footnote">
										以下是存档中提取的正文。可打开原始存档查看图片和页面排版。
									</p>
									{text.data?.paragraphs.map((paragraph, location) => ({ paragraph, location, id: `${active.task_id}:${location}` })).map(({ paragraph, location: index, id }) => (

										<section
											key={id}
											id={`search-paragraph-${index}`}
											tabIndex={-1}
											className={
												index === active.search_match?.paragraph_index
													? "search-matched-paragraph"
													: ""
											}
										>
											{index === active.search_match?.paragraph_index && (
												<span className="search-match-location">
													搜索匹配位置
												</span>
											)}
											<p>
												{index === active.search_match?.paragraph_index &&
												active.search_match ? (
													<Highlighted
														match={{
															...active.search_match,
															excerpt: paragraph,
															highlights:
																active.search_match.paragraph_highlights || [],
														}}
														fallback={paragraph}
													/>
												) : (
													paragraph
												)}
											</p>
										</section>
									))}
									<footer>
										<button
											className="search-secondary"
											type="button"
											onClick={returnToResults}
										>
											返回搜索结果
										</button>
									</footer>
								</article>
							)}
						</section>
					)}
				</>
			)}
		</section>
	);
}
