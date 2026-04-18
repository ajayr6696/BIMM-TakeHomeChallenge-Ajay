import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MockedProvider, type MockedResponse } from "@apollo/client/testing";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useMediaQuery } from "@mui/material";
import CarCard from "@/components/CarCard";
import CarInventory from "@/components/CarInventory";
import { ADD_CAR, GET_CARS } from "@/graphql/queries";

vi.mock("@mui/material", async () => {
  const actual = await vi.importActual<typeof import("@mui/material")>("@mui/material");
  return {
    ...actual,
    useMediaQuery: vi.fn(),
  };
});

const mockedUseMediaQuery = vi.mocked(useMediaQuery);

const initialCars = [
  {
    id: "1",
    make: "Toyota",
    model: "Camry",
    year: 2024,
    color: "Silver",
    mobile: "https://placehold.co/640x360",
    tablet: "https://placehold.co/1023x576",
    desktop: "https://placehold.co/1440x810",
    __typename: "Car" as const,
  },
  {
    id: "2",
    make: "Tesla",
    model: "Model 3",
    year: 2022,
    color: "White",
    mobile: "https://placehold.co/640x360",
    tablet: "https://placehold.co/1023x576",
    desktop: "https://placehold.co/1440x810",
    __typename: "Car" as const,
  },
  {
    id: "3",
    make: "Audi",
    model: "A4",
    year: 2026,
    color: "Blue",
    mobile: "https://placehold.co/640x360?text=Audi+A4+Mobile",
    tablet: "https://placehold.co/1023x576?text=Audi+A4+Tablet",
    desktop: "https://placehold.co/1440x810?text=Audi+A4+Desktop",
    __typename: "Car" as const,
  },
];

const updatedCars = [
  ...initialCars,
  {
    id: "4",
    make: "BMW",
    model: "M3",
    year: 2025,
    color: "Black",
    mobile: "https://placehold.co/640x360",
    tablet: "https://placehold.co/1023x576",
    desktop: "https://placehold.co/1440x810",
    __typename: "Car" as const,
  },
];

const firstCar = initialCars[0]!;

function renderInventory(mocks: ReadonlyArray<MockedResponse>) {
  return render(
    <MockedProvider mocks={mocks}>
      <CarInventory />
    </MockedProvider>
  );
}

function getRenderedImageAlts() {
  return screen.getAllByRole("img").map((image) => image.getAttribute("alt"));
}

describe("CarInventory", () => {
  beforeEach(() => {
    mockedUseMediaQuery.mockReset();
    mockedUseMediaQuery.mockReturnValue(false);
  });

  it("shows a loading state before the query resolves", () => {
    const mocks = [
      {
        request: { query: GET_CARS },
        result: { data: { cars: initialCars } },
        delay: 20,
      },
    ];

    renderInventory(mocks);

    expect(screen.getByRole("progressbar")).toBeInTheDocument();
  });

  it("shows a query error when the list request fails", async () => {
    const mocks = [
      {
        request: { query: GET_CARS },
        error: new Error("Inventory unavailable"),
      },
    ];

    renderInventory(mocks);

    expect(await screen.findByText("Inventory unavailable")).toBeInTheDocument();
  });

  it("uses the desktop image by default", async () => {
    const mocks = [
      {
        request: { query: GET_CARS },
        result: { data: { cars: initialCars } },
      },
    ];

    renderInventory(mocks);

    expect(await screen.findByText("2024 Toyota Camry")).toBeInTheDocument();
    expect(screen.getByAltText("2024 Toyota Camry")).toHaveAttribute(
      "src",
      firstCar.desktop
    );
  });

  it("uses the mobile image when the mobile breakpoint matches", () => {
    mockedUseMediaQuery.mockImplementation((query) => query === "(max-width:640px)");

    render(<CarCard car={firstCar} />);

    expect(screen.getByAltText("2024 Toyota Camry")).toHaveAttribute(
      "src",
      firstCar.mobile
    );
  });

  it("uses the tablet image when the tablet breakpoint matches", () => {
    mockedUseMediaQuery.mockImplementation(
      (query) => query === "(min-width:641px) and (max-width:1023px)"
    );

    render(<CarCard car={firstCar} />);

    expect(screen.getByAltText("2024 Toyota Camry")).toHaveAttribute(
      "src",
      firstCar.tablet
    );
  });

  it("filters by model and shows an empty state when nothing matches", async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: { query: GET_CARS },
        result: { data: { cars: initialCars } },
      },
    ];

    renderInventory(mocks);

    expect(await screen.findByText("2024 Toyota Camry")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Search by model"), "model");

    await waitFor(() => {
      expect(screen.queryByText("2024 Toyota Camry")).not.toBeInTheDocument();
    });
    expect(screen.getByText("2022 Tesla Model 3")).toBeInTheDocument();
    expect(screen.queryByText("2026 Audi A4")).not.toBeInTheDocument();

    await user.clear(screen.getByLabelText("Search by model"));
    await user.type(screen.getByLabelText("Search by model"), "roadster");

    await waitFor(() => {
      expect(screen.getByText("No cars match your current search.")).toBeInTheDocument();
    });
  });

  it("sorts cars by make and by year", async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: { query: GET_CARS },
        result: { data: { cars: initialCars } },
      },
    ];

    renderInventory(mocks);

    expect(await screen.findByText("2024 Toyota Camry")).toBeInTheDocument();
    expect(getRenderedImageAlts()).toEqual([
      "2026 Audi A4",
      "2024 Toyota Camry",
      "2022 Tesla Model 3",
    ]);

    await user.click(screen.getByLabelText("Sort cars"));
    await user.click(await screen.findByRole("option", { name: "Make (A-Z)" }));

    await waitFor(() => {
      expect(getRenderedImageAlts()).toEqual([
        "2026 Audi A4",
        "2022 Tesla Model 3",
        "2024 Toyota Camry",
      ]);
    });

    await user.click(screen.getByLabelText("Sort cars"));
    await user.click(await screen.findByRole("option", { name: "Year (Oldest)" }));

    await waitFor(() => {
      expect(getRenderedImageAlts()).toEqual([
        "2022 Tesla Model 3",
        "2024 Toyota Camry",
        "2026 Audi A4",
      ]);
    });
  });

  it("keeps add car disabled until the form is valid", async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: { query: GET_CARS },
        result: { data: { cars: initialCars } },
      },
    ];

    renderInventory(mocks);

    await screen.findByText("2024 Toyota Camry");

    const submitButton = screen.getByRole("button", { name: "Add Car" });
    expect(submitButton).toBeDisabled();

    await user.type(screen.getByLabelText("Make"), "BMW");
    await user.type(screen.getByLabelText("Model"), "M3");
    await user.type(screen.getByLabelText("Color"), "Black");
    expect(submitButton).toBeEnabled();

    await user.clear(screen.getByLabelText("Year"));
    await user.type(screen.getByLabelText("Year"), "1800");
    expect(submitButton).toBeDisabled();
  });

  it("adds a new car from the UI, refreshes the list, and resets the form", async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: { query: GET_CARS },
        result: { data: { cars: initialCars } },
      },
      {
        request: {
          query: ADD_CAR,
          variables: {
            make: "BMW",
            model: "M3",
            year: 2025,
            color: "Black",
          },
        },
        result: {
          data: {
            addCar: updatedCars[3],
          },
        },
      },
      {
        request: { query: GET_CARS },
        result: { data: { cars: updatedCars } },
      },
    ];

    renderInventory(mocks);

    expect(await screen.findByText("2024 Toyota Camry")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Make"), "BMW");
    await user.type(screen.getByLabelText("Model"), "M3");
    await user.clear(screen.getByLabelText("Year"));
    await user.type(screen.getByLabelText("Year"), "2025");
    await user.type(screen.getByLabelText("Color"), "Black");
    await user.click(screen.getByRole("button", { name: "Add Car" }));

    expect(await screen.findByText("2025 BMW M3")).toBeInTheDocument();
    expect(screen.getByLabelText("Make")).toHaveValue("");
    expect(screen.getByLabelText("Model")).toHaveValue("");
    expect(screen.getByLabelText("Year")).toHaveValue("2026");
    expect(screen.getByLabelText("Color")).toHaveValue("");
  });

  it("shows the mutation error when add car fails", async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: { query: GET_CARS },
        result: { data: { cars: initialCars } },
      },
      {
        request: {
          query: ADD_CAR,
          variables: {
            make: "BMW",
            model: "M3",
            year: 2025,
            color: "Black",
          },
        },
        result: {
          errors: [{ message: "Mutation failed" }],
        },
      },
    ];

    renderInventory(mocks);

    await screen.findByText("2024 Toyota Camry");

    await user.type(screen.getByLabelText("Make"), "BMW");
    await user.type(screen.getByLabelText("Model"), "M3");
    await user.clear(screen.getByLabelText("Year"));
    await user.type(screen.getByLabelText("Year"), "2025");
    await user.type(screen.getByLabelText("Color"), "Black");
    await user.click(screen.getByRole("button", { name: "Add Car" }));

    expect(await screen.findByText("Mutation failed")).toBeInTheDocument();
  });
});
