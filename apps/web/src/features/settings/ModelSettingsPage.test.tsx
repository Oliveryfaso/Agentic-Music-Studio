import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ModelSettingsPage } from "./ModelSettingsPage";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function show(state: string) {
  const fetcher=vi.fn().mockResolvedValue({ok:true,json:async()=>({data:{state,error_code:null}})});
  vi.stubGlobal("fetch",fetcher);
  const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});
  render(<QueryClientProvider client={client}><ModelSettingsPage/></QueryClientProvider>);
  return fetcher;
}
it("exposes real enable and removal steps without collecting secrets or auto checking",async()=>{
  const fetcher=show("not_configured");
  expect(await screen.findByText("未配置")).toBeInTheDocument();
  expect(screen.getByText("python3 scripts/configure_deepseek.py")).toBeInTheDocument();
  expect(screen.getByText(/--personal-beta --enable-deepseek/)).toBeInTheDocument();
  expect(screen.getByText("python3 scripts/configure_deepseek.py --clear")).toBeInTheDocument();
  expect(screen.getByRole("button",{name:"测试连接"})).toBeDisabled();
  expect(document.querySelector("input")).toBeNull();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(screen.getByText(/可能产生费用/)).toBeInTheDocument();
});
it("keeps configured separate from connection success and submits only explicit test",async()=>{
  const fetcher=show("configured");
  expect(await screen.findByText("已配置 · 未测试")).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(1);
  fetcher.mockResolvedValueOnce({ok:true,json:async()=>({data:{state:"connected",error_code:null}})});
  fireEvent.click(screen.getByRole("button",{name:"测试连接"}));
  expect(await screen.findByText("连接成功")).toBeInTheDocument();
  expect(fetcher).toHaveBeenNthCalledWith(2,"/api/v1/model-settings/check",expect.objectContaining({method:"POST",headers:{"X-Motif-Configuration-Check":"1"}}));
  expect(screen.getByText(/未验证生成能力/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"刷新配置状态"}));
  await waitFor(()=>expect(screen.getByText("已配置 · 未测试")).toBeInTheDocument());
});
it("renders sanitized failure with retry without losing setup help",async()=>{
  const fetcher=show("configured");
  await screen.findByText("已配置 · 未测试");
  fetcher.mockResolvedValueOnce({ok:true,json:async()=>({data:{state:"failed",error_code:"AUTHENTICATION_FAILED"}})});
  fireEvent.click(screen.getByRole("button",{name:"测试连接"}));
  expect(await screen.findByText("连接失败")).toBeInTheDocument();
  expect(screen.getByText(/密钥无效或没有访问权限/)).toBeInTheDocument();
  expect(screen.getByRole("button",{name:"测试连接"})).toBeEnabled();
});
it("does not mistake local service failure for a missing key",async()=>{
  const fetcher=show("configured");
  await screen.findByText("已配置 · 未测试");
  fetcher.mockRejectedValueOnce(new Error("mock sensitive upstream detail"));
  fireEvent.click(screen.getByRole("button",{name:"刷新配置状态"}));
  expect(await screen.findByText("无法读取配置状态")).toBeInTheDocument();
  expect(screen.queryByText("mock sensitive upstream detail")).not.toBeInTheDocument();
  expect(screen.queryByText("未配置")).not.toBeInTheDocument();
});
