import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, ChevronDown } from "lucide-react";
import { archiveTasksReadArchiveTask } from "@/client/sdk.gen";
import { readGenerated } from "../../api/client";
import { formatDate } from "../../utils/format";

export function SavedVersions({
	ids,
	count,
}: {
	ids: string[];
	count: number;
}): JSX.Element {
	const [expanded, setExpanded] = useState(false);
	const versions = useQuery({
		queryKey: ["archive-search-versions", ids],
		queryFn: () =>
			Promise.all(
				ids.map((task_id) =>
					readGenerated(archiveTasksReadArchiveTask({ path: { task_id } })),
				),
			),
		enabled: expanded,
		staleTime: 30000,
	});
	return (
		<div className="archive-search-versions">
			<button
				className="search-secondary"
				type="button"
				aria-expanded={expanded}
				onClick={() => setExpanded((value) => !value)}
			>
				查看 {count} 个保存版本
				<ChevronDown size={15} />
			</button>
			{expanded && (
				<div>
					{versions.isPending ? (
						<p>正在读取保存版本…</p>
					) : versions.isError ? (
						<p>
							暂时无法读取版本。
							<button
								className="text-button"
								type="button"
								onClick={() => void versions.refetch()}
							>
								重试
							</button>
						</p>
					) : (
						versions.data?.map((version) => (
							<div className="archive-search-version" key={version.task_id}>
								<span>{formatDate(version.created_at)}</span>
								{version.result?.view_url ? (
									<a
										className="text-button"
										href={version.result.view_url}
										target="_blank"
										rel="noopener noreferrer"
									>
										打开此版本
										<ArrowUpRight size={14} />
									</a>
								) : (
									<span>暂无网页存档</span>
								)}
							</div>
						))
					)}
				</div>
			)}
		</div>
	);
}
