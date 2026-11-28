import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Field, Notice, Page } from "../components/ui";

describe("components", () => {
  it("wires a field's label, hint and error for assistive technology", () => {
    render(<Field label="Organisation ID" hint="The tenant" error="Required" />);
    const input = screen.getByLabelText("Organisation ID");
    expect(input).toHaveProperty("ariaInvalid", "true");
    const described = input.getAttribute("aria-describedby")!.split(" ");
    expect(described.map((id) => document.getElementById(id)!.textContent)).toEqual(["The tenant", "Required"]);
  });

  it("announces errors as alerts and news as status", () => {
    render(
      <>
        <Notice kind="error">Failed</Notice>
        <Notice>Saved</Notice>
      </>,
    );
    expect(screen.getByRole("alert").textContent).toBe("Failed");
    expect(screen.getByRole("status").textContent).toBe("Saved");
  });

  it("moves focus to the page heading and names the window", () => {
    render(<Page title="Patients" intro="Find a patient" />);
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1, name: "Patients" }));
    expect(document.title).toBe("Patients · ASTEMIA Health");
  });
});
