from __future__ import annotations

import mimetypes
from html import escape
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse

from app.api.deps import get_archive_task_service
from app.models import (
    ArchiveTagRead,
    ArchiveTaskCreate,
    ArchiveTaskCreated,
    ArchiveTaskFileRead,
    ArchiveTaskFileUpdate,
    ArchiveTaskListRead,
    ArchiveTaskRead,
    ArchiveTaskUpdate,
)
from app.service import ArchiveTaskService


def create_router() -> APIRouter:
    router = APIRouter(tags=["archive-tasks"])

    @router.post(
        "/archive-tasks",
        response_model=ArchiveTaskCreated,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_archive_task(
        payload: ArchiveTaskCreate,
        request: Request,
    ) -> ArchiveTaskCreated:
        service = get_archive_task_service(request)
        task = await service.create_task(str(payload.url))
        return ArchiveTaskCreated(
            task_id=task.task_id,
            status=task.status,
            status_url=f"/api/v1/archive-tasks/{task.task_id}",
        )

    @router.get("/archive-tasks", response_model=ArchiveTaskListRead)
    async def list_archive_tasks(
        request: Request,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        include_read: bool = Query(default=False),
        tag: str | None = Query(default=None, max_length=80),
        tags: list[str] | None = Query(default=None, max_length=80),
        q: str | None = Query(default=None, max_length=240),
        title: str | None = Query(default=None, max_length=120),
        status_filter: Literal["running", "failed"] | None = Query(
            default=None,
            alias="status",
        ),
    ) -> ArchiveTaskListRead:
        service = get_archive_task_service(request)
        return service.list_tasks(
            limit,
            offset=offset,
            include_read=include_read,
            tag=tag,
            tags=tags,
            query=q,
            title_query=title,
            status_filter=status_filter,
        )

    @router.get("/archive-tags", response_model=list[ArchiveTagRead])
    async def list_archive_tags(request: Request) -> list[ArchiveTagRead]:
        service = get_archive_task_service(request)
        return service.list_tags()

    @router.get("/archive-tasks/{task_id}", response_model=ArchiveTaskRead)
    async def read_archive_task(task_id: str, request: Request) -> ArchiveTaskRead:
        service = get_archive_task_service(request)
        task = service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Archive task not found.")
        return task

    @router.patch("/archive-tasks/{task_id}", response_model=ArchiveTaskRead)
    async def update_archive_task(
        task_id: str,
        payload: ArchiveTaskUpdate,
        request: Request,
    ) -> ArchiveTaskRead:
        service = get_archive_task_service(request)
        task = service.update_task_metadata(
            task_id,
            custom_title_provided="custom_title" in payload.model_fields_set,
            custom_title=payload.custom_title,
            tags=payload.tags,
        )
        if task is None:
            raise HTTPException(status_code=404, detail="Archive task not found.")
        return task

    @router.get("/archive-tasks/{task_id}/file-list", response_model=list[ArchiveTaskFileRead])
    async def list_archive_task_files(
        task_id: str,
        request: Request,
    ) -> list[ArchiveTaskFileRead]:
        service = get_archive_task_service(request)
        task = service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Archive task not found.")
        return [
            archive_file_response(task, path, service)
            for path in service.list_result_files(task)
        ]

    @router.post(
        "/archive-tasks/{task_id}/files",
        response_model=ArchiveTaskFileRead,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_archive_task_file(
        task_id: str,
        request: Request,
        file_name: str = Query(..., min_length=1, max_length=240),
    ) -> ArchiveTaskFileRead:
        service = get_archive_task_service(request)
        task = service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Archive task not found.")
        try:
            path = await service.upload_task_file(task, file_name, request.stream())
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return archive_file_response(task, path, service)

    @router.patch(
        "/archive-tasks/{task_id}/files/{file_name:path}",
        response_model=ArchiveTaskFileRead,
    )
    async def update_archive_task_file(
        task_id: str,
        file_name: str,
        payload: ArchiveTaskFileUpdate,
        request: Request,
    ) -> ArchiveTaskFileRead:
        service = get_archive_task_service(request)
        task = service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Archive task not found.")
        try:
            path = service.update_task_file_display_name(
                task,
                file_name,
                payload.display_name,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return archive_file_response(task, path, service)

    @router.delete(
        "/archive-tasks/{task_id}/files/{file_name:path}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_archive_task_file(
        task_id: str,
        file_name: str,
        request: Request,
    ) -> None:
        service = get_archive_task_service(request)
        task = service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Archive task not found.")
        try:
            deleted = service.delete_task_file(task, file_name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=410, detail="Archive file is missing.")

    @router.post("/archive-tasks/{task_id}/mark-read", response_model=ArchiveTaskRead)
    async def mark_archive_task_read(task_id: str, request: Request) -> ArchiveTaskRead:
        service = get_archive_task_service(request)
        task = service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Archive task not found.")
        service.mark_task_read(task_id)
        updated = service.get_task(task_id)
        if updated is None:
            raise HTTPException(status_code=404, detail="Archive task not found.")
        return updated

    @router.post(
        "/archive-tasks/{task_id}/rearchive",
        response_model=ArchiveTaskRead,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def rearchive_task(task_id: str, request: Request) -> ArchiveTaskRead:
        service = get_archive_task_service(request)
        try:
            return await service.rearchive_task(task_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post(
        "/archive-tasks/{task_id}/continue-video",
        response_model=ArchiveTaskRead,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def continue_archive_video(task_id: str, request: Request) -> ArchiveTaskRead:
        service = get_archive_task_service(request)
        try:
            return await service.continue_after_browser_login(task_id)
        except ValueError as exc:
            if str(exc) == "Archive task not found.":
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/archive-tasks/{task_id}/open-browser", status_code=status.HTTP_202_ACCEPTED)
    async def open_archive_task_in_browser(task_id: str, request: Request) -> dict[str, str]:
        service = get_archive_task_service(request)
        try:
            await service.open_task_in_browser(task_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"desktop_url": request.app.state.settings.desktop_url}

    @router.delete("/archive-tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_archive_task(task_id: str, request: Request) -> None:
        service = get_archive_task_service(request)
        try:
            deleted = service.delete_task(task_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="Archive task not found.")

    @router.get("/archive-tasks/{task_id}/result")
    async def download_archive_result(task_id: str, request: Request) -> FileResponse:
        return read_archive_result_file(
            task_id=task_id,
            request=request,
            content_disposition_type="attachment",
        )

    @router.get("/archive-tasks/{task_id}/result/view")
    async def view_archive_result(task_id: str, request: Request) -> FileResponse:
        return read_archive_result_file(
            task_id=task_id,
            request=request,
            content_disposition_type="inline",
        )

    @router.get(
        "/archive-tasks/{task_id}/files",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    async def list_archive_files(task_id: str, request: Request) -> HTMLResponse:
        service = get_archive_task_service(request)
        task = read_existing_task(service, task_id)
        files = service.list_result_files(task)
        if not files:
            raise HTTPException(status_code=410, detail="Archive files are missing.")
        service.mark_task_read(task_id)
        return HTMLResponse(render_file_index(task, files, service))

    @router.get("/archive-tasks/{task_id}/files/{file_name:path}", include_in_schema=False)
    async def read_archive_file(
        task_id: str,
        file_name: str,
        request: Request,
        download: bool = Query(default=False),
    ) -> FileResponse:
        service = get_archive_task_service(request)
        task = read_existing_task(service, task_id)
        try:
            result_path = service.get_task_file_path(task, file_name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not result_path.exists():
            raise HTTPException(status_code=410, detail="Archive file is missing.")
        media_type = mimetypes.guess_type(result_path.name)[0] or "application/octet-stream"
        return FileResponse(
            result_path,
            media_type=media_type,
            filename=service.task_file_display_name(task, result_path),
            content_disposition_type="attachment" if download else "inline",
        )

    @router.get("/archive-tasks/{task_id}/result/video")
    async def download_video_result(task_id: str, request: Request) -> FileResponse:
        service = get_archive_task_service(request)
        task = service.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Archive task not found.")
        if task.result is None:
            raise HTTPException(
                status_code=409,
                detail="Archive task is not finished yet.",
            )
        if task.result.video_file_name is None:
            raise HTTPException(status_code=404, detail="Video file not found.")

        result_path = service.get_video_result_path(task)
        if not result_path.exists():
            raise HTTPException(status_code=410, detail="Video file is missing.")
        return FileResponse(
            result_path,
            media_type="application/octet-stream",
            filename=service.task_file_display_name(task, result_path),
            content_disposition_type="attachment",
        )

    def read_archive_result_file(
        task_id: str,
        request: Request,
        content_disposition_type: str,
    ) -> FileResponse:
        service = get_archive_task_service(request)
        task = read_finished_task(service, task_id)

        try:
            result_path = service.get_result_path(task)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not result_path.exists():
            raise HTTPException(status_code=410, detail="Archive file is missing.")
        return FileResponse(
            result_path,
            media_type="text/html",
            filename=service.task_file_display_name(task, result_path),
            content_disposition_type=content_disposition_type,
        )

    return router


def read_finished_task(service: ArchiveTaskService, task_id: str) -> ArchiveTaskRead:
    task = service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Archive task not found.")
    if task.result is None:
        raise HTTPException(
            status_code=409,
            detail="Archive task is not finished yet.",
        )
    return task


def read_existing_task(service: ArchiveTaskService, task_id: str) -> ArchiveTaskRead:
    task = service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Archive task not found.")
    return task


def render_file_index(
    task: ArchiveTaskRead,
    files: list[Path],
    service: ArchiveTaskService,
) -> str:
    rows = "\n".join(render_file_row(task, path, service) for path in files)
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>存档文件</title>
    <style>
      :root {{
        color-scheme: light;
        --bg: #f4f6f3;
        --surface: #ffffff;
        --text: #202522;
        --muted: #66716c;
        --border: #dce3de;
        --border-strong: #c5cec8;
        --primary: #147a6d;
        --primary-strong: #0e6157;
        font-family: -apple-system, "SF Pro Text", "PingFang SC", "Noto Sans SC", sans-serif;
      }}
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; background: var(--bg); color: var(--text); font-size: 15px; line-height: 1.5; }}
      main {{ max-width: 1040px; margin: 0 auto; padding: 36px 24px 64px; }}
      h1 {{ margin: 0 0 8px; font-size: 22px; line-height: 1.25; }}
      .task-id {{ margin-bottom: 22px; color: var(--muted); overflow-wrap: anywhere; }}
      table {{ width: 100%; border-collapse: collapse; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
      th, td {{ padding: 14px 16px; border-bottom: 1px solid var(--border); text-align: left; }}
      th {{ color: var(--muted); font-size: 13px; font-weight: 680; background: #f8f9f7; }}
      tr:last-child td {{ border-bottom: 0; }}
      .name {{ overflow-wrap: anywhere; }}
      .size {{ width: 120px; color: var(--muted); white-space: nowrap; }}
      .actions {{ width: 140px; white-space: nowrap; }}
      a {{ color: var(--primary-strong); text-decoration: none; font-weight: 650; }}
      a:hover {{ text-decoration: underline; }}
      a + a {{ margin-left: 14px; }}
      @media (max-width: 720px) {{
        main {{ padding: 28px 16px 48px; }}
        table, tbody, tr, td {{ display: block; width: 100%; }}
        thead {{ display: none; }}
        tr {{ padding: 12px 14px; border-bottom: 1px solid var(--border); }}
        tr:last-child {{ border-bottom: 0; }}
        td {{ padding: 5px 0; border-bottom: 0; }}
        .size, .actions {{ width: 100%; }}
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>存档文件</h1>
      <div class="task-id">{escape(task.task_id)}</div>
      <table>
        <thead>
          <tr>
            <th>文件名</th>
            <th>大小</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
{rows}
        </tbody>
      </table>
    </main>
  </body>
</html>
"""


def render_file_row(
    task: ArchiveTaskRead,
    path: Path,
    service: ArchiveTaskService,
) -> str:
    task_id = task.task_id
    encoded_name = quote(path.name)
    href = f"/api/v1/archive-tasks/{quote(task_id)}/files/{encoded_name}"
    download_href = f"{href}?download=true"
    display_name = service.task_file_display_name(task, path)
    return f"""          <tr>
            <td class="name"><a href="{href}" title="{escape(path.name)}">{escape(display_name)}</a></td>
            <td class="size">{format_file_size(path.stat().st_size)}</td>
            <td class="actions"><a href="{href}">打开</a><a href="{download_href}">下载</a></td>
          </tr>"""


def archive_file_response(
    task: ArchiveTaskRead,
    path: Path,
    service: ArchiveTaskService,
) -> ArchiveTaskFileRead:
    task_id = task.task_id
    encoded_name = quote(path.name)
    href = f"/api/v1/archive-tasks/{quote(task_id)}/files/{encoded_name}"
    source_type = service.task_file_source_type(task, path)
    return ArchiveTaskFileRead(
        file_name=path.name,
        display_name=service.task_file_display_name(task, path),
        tool=source_type,
        source_type=source_type,
        size_bytes=path.stat().st_size,
        view_url=href,
        download_url=f"{href}?download=true",
    )


def format_file_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{size} B"
        value /= 1024
    return f"{size} B"


router = create_router()
