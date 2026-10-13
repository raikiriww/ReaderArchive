import { Plus, X } from "lucide-react";
import { type KeyboardEvent, type RefObject, useState } from "react";
import type { ArchiveTag } from "../../types/domain";
import { cleanTag } from "../../utils/tags";

interface TagEditorProps {
  tags: string[];
  allTags: ArchiveTag[];
  onChange(tags: string[]): void;
  inputRef?: RefObject<HTMLInputElement | null>;
}

/** Autocomplete from existing tags, or create a new one. No suggestions are pre-selected. */
export function TagEditor({ tags, allTags, onChange, inputRef }: TagEditorProps): JSX.Element {
  const [value, setValue] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const has = new Set(tags.map((tag) => tag.toLowerCase()));
  const typed = cleanTag(value);
  const q = typed.toLowerCase();
  const matches = allTags.filter(
    (tag) => !has.has(tag.name.toLowerCase()) && (!q || tag.name.toLowerCase().includes(q)),
  ).slice(0, 7);
  const canCreate = Boolean(q) && !has.has(q) && !allTags.some((tag) => tag.name.toLowerCase() === q);
  const options: Array<{ name: string; count?: number; create?: boolean }> = [
    ...matches.map((tag) => ({ name: tag.name, count: tag.task_count })),
    ...(canCreate ? [{ name: typed, create: true }] : []),
  ];
  const activeIndex = Math.min(active, Math.max(0, options.length - 1));

  function add(name: string | undefined): void {
    const tag = cleanTag(name || "");
    if (tag && !has.has(tag.toLowerCase())) onChange([...tags, tag]);
    setValue("");
    setActive(0);
  }

  function keyDown(event: KeyboardEvent<HTMLInputElement>): void {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive(Math.min(options.length - 1, activeIndex + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive(Math.max(0, activeIndex - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      event.stopPropagation();
      const choice = (open ? options[activeIndex]?.name : undefined) ?? typed;
      if (choice) add(choice);
    } else if (event.key === "Backspace" && !value && tags.length) {
      onChange(tags.slice(0, -1));
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      setValue("");
      event.currentTarget.blur();
    }
  }

  return (
    <div className="rd-tags">
      {tags.map((tag) => (
        <span className="rd-tag" key={tag}>
          <span>#{tag}</span>
          <button
            type="button"
            aria-label={`移除 ${tag}`}
            title={`移除 ${tag}`}
            onClick={() => onChange(tags.filter((item) => item !== tag))}
          >
            <X size={11} strokeWidth={2.4} aria-hidden="true" />
          </button>
        </span>
      ))}
      <div className="rd-tag-input-wrap">
        <input
          ref={inputRef}
          className="rd-tag-input"
          value={value}
          placeholder="+ 标签  T"
          aria-label="添加标签"
          autoComplete="off"
          onChange={(event) => {
            setValue(event.target.value);
            setActive(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={keyDown}
        />
        {open && options.length ? (
          <div className="rd-tag-menu" role="listbox">
            {options.map((option, index) => (
              <button
                key={`${option.create ? "new:" : ""}${option.name}`}
                type="button"
                role="option"
                aria-selected={index === activeIndex}
                className={index === activeIndex ? "active" : ""}
                onMouseDown={(event) => {
                  event.preventDefault();
                  add(option.name);
                }}
              >
                {option.create ? (
                  <>
                    <Plus size={12} aria-hidden="true" />
                    新建「{option.name}」
                  </>
                ) : (
                  <>
                    #{option.name}
                    <span>{option.count}</span>
                  </>
                )}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
