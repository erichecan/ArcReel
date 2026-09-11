import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "wouter";
import { ListChecks, Users, Landmark, Package } from "lucide-react";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useWorkflowStore } from "@/stores/workflow-store";
import { errMsg } from "@/utils/async";
import {
  ROUTE_APP_PROJECTS,
  WORKSPACE_ROUTE_CHARACTERS,
  WORKSPACE_ROUTE_SCENES,
  WORKSPACE_ROUTE_PROPS,
} from "@/app-routes";

interface AdAssetPlanGateProps {
  projectName: string;
  /** 确认成功后调用（通常刷新项目数据）。 */
  onConfirmed: () => void | Promise<void>;
}

const CARD_BG =
  "linear-gradient(180deg, oklch(0.22 0.012 265 / 0.55), oklch(0.19 0.010 265 / 0.40))";
const CARD_SHADOW =
  "inset 0 1px 0 oklch(1 0 0 / 0.04), 0 8px 24px -10px oklch(0 0 0 / 0.5)";

const ASSET_LINKS = [
  { segment: WORKSPACE_ROUTE_CHARACTERS, labelKey: "characters", Icon: Users },
  { segment: WORKSPACE_ROUTE_SCENES, labelKey: "scenes", Icon: Landmark },
  { segment: WORKSPACE_ROUTE_PROPS, labelKey: "props", Icon: Package },
] as const;

/**
 * ad 项目脚本生成前的资产清单确认门禁：反复出现的角色/场景/道具没有参考图时，
 * 各视频单元的生成画面会互相对不上（同一个人物、场景在不同镜头里长得不一样）。
 * 工作流状态机在 `next_action.type === "confirm_ad_asset_plan"` 时挡在这里，
 * 直到用户登记至少一项资产，或显式确认本项目不需要额外资产。
 */
export function AdAssetPlanGate({ projectName, onConfirmed }: AdAssetPlanGateProps) {
  const { t } = useTranslation(["dashboard", "common"]);
  const [, setLocation] = useLocation();
  const checkboxId = useId();

  const plan = useWorkflowStore((s) => s.plan);
  const planKey = useWorkflowStore((s) => s.planKey);
  const refreshPlan = useWorkflowStore((s) => s.refreshPlan);

  const [noAdditionalAssets, setNoAdditionalAssets] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!projectName) return;
    void refreshPlan(projectName, 1);
  }, [projectName, refreshPlan]);

  // ad 恒单集：episode 固定为 1，与 workflow-store 内部的 planKey(project, episode) 拼法一致。
  const isCurrentPlan = planKey === `${projectName}::1`;
  if (!isCurrentPlan || !plan) return null;
  if (plan.status.next_action.type !== "confirm_ad_asset_plan") return null;

  const handleConfirm = async () => {
    setSubmitting(true);
    try {
      await API.confirmAdAssetPlan(projectName, noAdditionalAssets);
      useAppStore.getState().pushToast(t("dashboard:ad_asset_plan_confirmed_toast"), "success");
      await onConfirmed();
      await refreshPlan(projectName, 1);
    } catch (err) {
      useAppStore
        .getState()
        .pushToast(t("dashboard:ad_asset_plan_confirm_failed", { message: errMsg(err) }), "error");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section
      className="relative overflow-hidden rounded-2xl p-5"
      style={{
        border: "1px solid var(--color-accent-soft)",
        background: CARD_BG,
        boxShadow: CARD_SHADOW,
      }}
    >
      <span
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-px"
        style={{
          background: "linear-gradient(90deg, transparent, var(--color-accent-soft), transparent)",
        }}
      />

      <div className="mb-2 flex items-center gap-2.5">
        <ListChecks className="h-4 w-4" style={{ color: "var(--color-accent-2)" }} />
        <h3
          className="display-serif text-[15px] font-semibold tracking-tight"
          style={{ color: "var(--color-text)" }}
        >
          {t("dashboard:ad_asset_plan_title")}
        </h3>
      </div>
      <p className="text-[12.5px] leading-[1.6]" style={{ color: "var(--color-text-3)" }}>
        {t("dashboard:ad_asset_plan_hint")}
      </p>

      <div className="mt-3.5 flex flex-wrap gap-2">
        {ASSET_LINKS.map(({ segment, labelKey, Icon }) => (
          <button
            key={segment}
            type="button"
            onClick={() => setLocation(`${ROUTE_APP_PROJECTS}/${projectName}/${segment}`)}
            className="focus-ring inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12.5px] transition-colors hover:border-[var(--color-accent-soft)]"
            style={{
              border: "1px solid var(--color-hairline)",
              color: "var(--color-text-2)",
              background: "oklch(0.20 0.011 265 / 0.5)",
            }}
          >
            <Icon className="h-3.5 w-3.5" />
            {t(`dashboard:${labelKey}`)}
          </button>
        ))}
      </div>

      <div className="mt-4 flex items-start gap-2">
        <input
          id={checkboxId}
          type="checkbox"
          checked={noAdditionalAssets}
          onChange={(e) => setNoAdditionalAssets(e.target.checked)}
          disabled={submitting}
          className="focus-ring mt-0.5 h-3.5 w-3.5 accent-[var(--color-accent)]"
        />
        <label
          htmlFor={checkboxId}
          className="cursor-pointer select-none text-[12.5px]"
          style={{ color: "var(--color-text-2)" }}
        >
          {t("dashboard:ad_asset_plan_no_additional_label")}
        </label>
      </div>

      <button
        type="button"
        onClick={() => void handleConfirm()}
        disabled={submitting}
        className="focus-ring mt-4 inline-flex items-center gap-1.5 rounded-md px-4 py-2 text-[13px] font-medium transition-transform disabled:cursor-not-allowed disabled:opacity-50"
        style={{
          color: "oklch(0.14 0 0)",
          background: "linear-gradient(135deg, var(--color-accent-2), var(--color-accent))",
          boxShadow:
            "inset 0 1px 0 oklch(1 0 0 / 0.35), 0 6px 18px -4px var(--color-accent-glow), 0 0 0 1px var(--color-accent-soft)",
        }}
      >
        {submitting ? t("dashboard:ad_asset_plan_confirming") : t("dashboard:ad_asset_plan_confirm_button")}
      </button>
    </section>
  );
}
