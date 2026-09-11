import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { API } from "@/api";
import { useWorkflowStore } from "@/stores/workflow-store";
import { AdAssetPlanGate } from "./AdAssetPlanGate";
import { makePlan } from "@/test/factories";
import type { WorkflowStatus } from "@/types/workflow";

function statusWithAction(actionType: WorkflowStatus["next_action"]["type"]): WorkflowStatus {
  return {
    schema_version: 1,
    project_revision: "sha256-v1:project",
    source_revision: null,
    project: { content_mode: "ad", generation_mode: "reference_video", grid_storyboard: false },
    target: { episode: 1, script: "scripts/episode_1.json", script_filename: "episode_1.json", source: "source/episode_1.txt" },
    state: "ASSET_INVENTORY",
    blockers: [],
    gates: {},
    artifacts: {},
    next_action: {
      type: actionType,
      args: {},
      requested_ids: [],
      requires_confirmation: false,
      reason: "test",
    },
  };
}

beforeEach(() => {
  useWorkflowStore.getState().resetTarget();
});

describe("AdAssetPlanGate", () => {
  it("next_action 不是 confirm_ad_asset_plan 时不渲染", async () => {
    vi.spyOn(API, "getWorkflowPlan").mockResolvedValue(
      makePlan({ status: statusWithAction("generate_script") }),
    );
    render(<AdAssetPlanGate projectName="proj" onConfirmed={vi.fn()} />);
    await waitFor(() => expect(useWorkflowStore.getState().planKey).toBe("proj::1"));
    expect(screen.queryByText("资产清单确认")).not.toBeInTheDocument();
  });

  it("next_action 是 confirm_ad_asset_plan 时渲染确认卡片", async () => {
    vi.spyOn(API, "getWorkflowPlan").mockResolvedValue(
      makePlan({ status: statusWithAction("confirm_ad_asset_plan") }),
    );
    render(<AdAssetPlanGate projectName="proj" onConfirmed={vi.fn()} />);
    expect(await screen.findByText("资产清单确认")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /角色/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /场景/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /道具/ })).toBeInTheDocument();
  });

  it("勾选「不需要额外资产」并确认时把 no_additional_assets 传给接口，成功后回调并重新拉计划", async () => {
    vi.spyOn(API, "getWorkflowPlan").mockResolvedValue(
      makePlan({ status: statusWithAction("confirm_ad_asset_plan") }),
    );
    const confirmSpy = vi.spyOn(API, "confirmAdAssetPlan").mockResolvedValue({
      no_additional_assets: true,
      counts: { characters: 0, scenes: 0, props: 0 },
    });
    const onConfirmed = vi.fn();
    render(<AdAssetPlanGate projectName="proj" onConfirmed={onConfirmed} />);

    await screen.findByText("资产清单确认");
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "确认资产清单" }));

    await waitFor(() => expect(confirmSpy).toHaveBeenCalledWith("proj", true));
    await waitFor(() => expect(onConfirmed).toHaveBeenCalled());
  });

  it("确认失败时提示错误、不调用回调", async () => {
    vi.spyOn(API, "getWorkflowPlan").mockResolvedValue(
      makePlan({ status: statusWithAction("confirm_ad_asset_plan") }),
    );
    vi.spyOn(API, "confirmAdAssetPlan").mockRejectedValue(new Error("还没有登记任何资产"));
    const onConfirmed = vi.fn();
    render(<AdAssetPlanGate projectName="proj" onConfirmed={onConfirmed} />);

    await screen.findByText("资产清单确认");
    fireEvent.click(screen.getByRole("button", { name: "确认资产清单" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "确认资产清单" })).toBeEnabled());
    expect(onConfirmed).not.toHaveBeenCalled();
  });
});
