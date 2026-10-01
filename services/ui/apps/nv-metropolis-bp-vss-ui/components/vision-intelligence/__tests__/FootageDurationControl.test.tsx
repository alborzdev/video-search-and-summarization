// SPDX-License-Identifier: MIT

import React, { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { FootageDurationControl } from "../FootageDurationControl";

function Control() {
  const [seconds, setSeconds] = useState<number | null>(3);
  return <FootageDurationControl seconds={seconds} onChange={setSeconds} />;
}

it("shows the frame budget and explains sparse sampling for longer intervals", () => {
  render(<Control />);
  const input = screen.getByRole("spinbutton", { name: "Seconds of footage" });
  expect(input).toHaveValue(3);
  expect(screen.getByText("Up to 3 frames")).toBeInTheDocument();
  fireEvent.change(input, { target: { value: "2" } });
  expect(screen.getByText("Up to 2 frames")).toBeInTheDocument();
  fireEvent.change(input, { target: { value: "60" } });
  expect(screen.getByText("Up to 20 frames")).toBeInTheDocument();
  expect(screen.getByText("Sampling is capped at 20 frames across the full interval.")).toBeInTheDocument();
});

it.each(["", "0", "61", "2.5"])("explains invalid duration %s without advertising a frame budget", (value) => {
  render(<Control />);
  const input = screen.getByRole("spinbutton", { name: "Seconds of footage" });
  fireEvent.change(input, { target: { value } });
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByText("Choose 1–60 seconds")).toBeInTheDocument();
  expect(input).toBeInvalid();
});
