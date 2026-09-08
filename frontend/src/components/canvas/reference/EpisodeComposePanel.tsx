import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Download, Film, Loader2 } from "lucide-react";
import { API } from "@/api";

export interface EpisodeComposePanelProps {
  projectName: string;
  episode: number;
  /** 合成任务是否正在跑（渲染中）。 */
  busy: boolean;
  /**
   * 「一键成片」完成的失效信号（`referenceVideoComposeRevision`）：每次自增都重新
   * 探测一次成片是否存在，并让 `<video>` 拿到新版本而不是命中浏览器缓存。
   */
  revision: number;
}

/** 与 `lib.episode_paths.episode_final_cut_relpath` 同一路径约定——单一真相源在后端，
 *  这里只是按相同规则拼字符串来定位同一份文件。 */
function episodeFinalCutRelpath(episode: number): string {
  return `presentations/episode_${episode}/final_cut.mp4`;
}

type ProbeStatus = "checking" | "ready" | "missing";

/**
 * 按 `url` 挂载：换一个 url（合成完成后 revision 自增）就是全新的组件实例，天然拿到
 * 干净的初始探测态，不需要在 effect 里手动把状态拨回 "checking"。
 */
function ComposePreview({
  url,
  label,
  downloadLabel,
}: {
  url: string;
  label: string;
  downloadLabel: string;
}) {
  const [status, setStatus] = useState<ProbeStatus>("checking");

  return (
    <div
      className="flex items-center gap-3 border-b border-[var(--color-hairline-soft)] bg-[oklch(0.19_0.012_250_/_0.4)] px-5 py-2"
      hidden={status !== "ready"}
    >
      <Film className="h-3.5 w-3.5 shrink-0 text-[var(--color-text-3)]" aria-hidden="true" />
      <span className="shrink-0 text-[11.5px] font-medium text-[var(--color-text-2)]">{label}</span>
      <video
        src={url}
        controls
        preload="metadata"
        className="h-10 max-w-[200px] rounded"
        onLoadedMetadata={() => setStatus("ready")}
        onError={() => setStatus("missing")}
      >
        <track kind="captions" />
      </video>
      {status === "ready" && (
        <a
          href={url}
          download
          className="focus-ring inline-flex items-center gap-1.5 rounded-md border border-[var(--color-hairline)] bg-[oklch(0.22_0.011_265_/_0.5)] px-2.5 py-1 text-[11.5px] text-[var(--color-text-2)] transition-colors hover:bg-[oklch(0.26_0.013_265_/_0.7)] hover:text-[var(--color-text)]"
        >
          <Download className="h-3.5 w-3.5" aria-hidden="true" />
          <span>{downloadLabel}</span>
        </a>
      )}
    </div>
  );
}

/** 成片预览卡片：没渲染过时不占地方，渲染中显示进度，渲染完显示播放器 + 下载。 */
export function EpisodeComposePanel({ projectName, episode, busy, revision }: EpisodeComposePanelProps) {
  const { t } = useTranslation("dashboard");
  const url = API.getFileUrl(projectName, episodeFinalCutRelpath(episode), revision || undefined);

  if (busy) {
    return (
      <div className="flex items-center gap-2 border-b border-[var(--color-hairline-soft)] bg-[oklch(0.19_0.012_250_/_0.4)] px-5 py-2 text-[11.5px] text-[var(--color-text-3)]">
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
        <span>{t("reference_compose_rendering")}</span>
      </div>
    );
  }

  return (
    <ComposePreview
      key={url}
      url={url}
      label={t("reference_compose_preview_label")}
      downloadLabel={t("reference_compose_download")}
    />
  );
}
