import { render, screen } from "@testing-library/react";
import { Confidence, Status } from "../components/common/States";
describe("operational status components", () => {
  it("renders accessible classification confidence", () => {
    render(<Confidence value={0.94} />);
    expect(screen.getByText("94%")).toHaveClass("good");
  });
  it("formats workflow states", () => {
    render(<Status value="IN_REVIEW" />);
    expect(screen.getByText("IN REVIEW")).toBeInTheDocument();
  });
});
