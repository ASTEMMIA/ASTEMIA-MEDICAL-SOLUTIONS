import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearToken } from "../api";
import { App } from "../App";
import { SessionProvider } from "../session";

const ME = {
  subject: "clinician@pilot.astemia.local",
  tenant_id: "t",
  tenant_name: "ASTEMIA Pilot Hospital (synthetic)",
  roles: ["clinician"],
  capabilities: ["chart:read", "note:sign"],
  practitioner_id: "p",
  display_name: "Dr Clinician One",
};

function routes(url: string, init?: RequestInit): Response {
  if (url.startsWith("/v1/dev/accounts")) {
    return Response.json([{ subject: ME.subject, display_name: ME.display_name, roles: ME.roles }]);
  }
  if (url === "/v1/dev/sign-in") {
    expect(JSON.parse(String(init?.body)).subject).toBe(ME.subject);
    return Response.json({ access_token: "tok", token_type: "Bearer", expires_in: 3600 });
  }
  if (url === "/v1/me") return Response.json(ME);
  return new Response(null, { status: 404 });
}

function renderApp(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SessionProvider>
        <App />
      </SessionProvider>
    </MemoryRouter>,
  );
}

describe("the app", () => {
  beforeEach(() => {
    clearToken();
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => Promise.resolve(routes(url, init))));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("signs in through the development picker, shows who and where, and signs out", async () => {
    renderApp();
    expect(screen.getByText(/Development sign-in/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show accounts" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Welcome, Dr Clinician One" })).toBeTruthy();
    expect(screen.getByLabelText("Organisation").textContent).toBe(ME.tenant_name);
    expect(screen.getByRole("navigation", { name: "Main" })).toBeTruthy();
    fireEvent.click(screen.getByRole("link", { name: "My account" }));
    expect(await screen.findByText("Sign clinical notes")).toBeTruthy();
    expect(screen.getByText("Read the charts of patients in your care")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in to ASTEMIA Health" })).toBeTruthy();
  });

  it("explains an unknown organisation and a failed sign-in", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(
          url.startsWith("/v1/dev/accounts")
            ? Response.json([])
            : Response.json({ error: { code: "unauthenticated", message: "no" } }, { status: 401 }),
        ),
      ),
    );
    renderApp();
    fireEvent.click(screen.getByRole("button", { name: "Show accounts" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/No accounts were found/);
  });

  it("returns to sign-in, saying why, when the session ends by itself", async () => {
    sessionStorage.setItem("astemia.token", "expired");
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(Response.json({ error: { code: "unauthenticated", message: "expired" } }, { status: 401 }))),
    );
    renderApp("/account");
    await waitFor(() => expect(screen.getByText(/Your session ended/)).toBeTruthy());
  });
});
