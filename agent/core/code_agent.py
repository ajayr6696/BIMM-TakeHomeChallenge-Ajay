from __future__ import annotations

from agent.core.llm import LLMError, call_llm, must_parse_json, shorten_for_prompt
from agent.core.models import GeneratedFile, Plan
from agent.prompts.prompt_loader import load_prompt_template

PROJECT_CONSTRAINTS = load_prompt_template("project_constraints.txt")


class CodeAgent:
    """
    CodeAgent generates concrete file contents from a plan.

    Output is STRICT JSON describing files to write. The orchestrator writes them into
    the copied output project under generated-app/.
    """

    def __init__(self, offline: bool) -> None:
        """Workflow 4: Configure whether code generation should use the LLM or fallback templates."""
        self._offline = offline

    def generate(self, spec_text: str, plan: Plan) -> list[GeneratedFile]:
        """Workflow 4A: Generate the allowed files and fall back if model output is unsafe."""
        allowed = set(plan.components + plan.tests + ["src/App.tsx"])

        if not self._offline:
            prompt = self._build_prompt(spec_text, plan)
            try:
                data = must_parse_json(call_llm(prompt))
                files: list[GeneratedFile] = []
                for f in data["files"]:
                    path = str(f["path"])
                    if path in allowed:
                        files.append(GeneratedFile(path=path, content=str(f["content"])))
                if files and _is_valid_generation(files, allowed):
                    return files
            except (LLMError, KeyError, TypeError, ValueError):
                pass

        return [f for f in _fallback_files() if f.path in allowed]

    def _build_prompt(self, spec_text: str, plan: Plan) -> str:
        """Workflow 4B: Build the constrained prompt for the code-generation model call."""
        trimmed_spec = shorten_for_prompt(spec_text, 4000)
        plan_file_list = "\n".join(f"- {path}" for path in plan.components + plan.tests)
        ordered_steps = "\n".join(
            f"{step.order}. {step.title} | depends_on={step.depends_on} | outputs={step.outputs}"
            for step in plan.steps
        )
        return (
            load_prompt_template("code_prompt.txt")
            .replace("__PROJECT_CONSTRAINTS__", PROJECT_CONSTRAINTS)
            .replace("__PLAN_FILE_LIST__", plan_file_list)
            .replace("__ORDERED_STEPS__", ordered_steps)
            .replace("__SPEC_TEXT__", trimmed_spec)
            .replace("__PLAN_TEXT__", str(plan))
        )


def _fallback_files() -> list[GeneratedFile]:
    """Workflow fallback 1: Return the deterministic file set used when LLM output is skipped."""
    return [
        GeneratedFile(path="src/hooks/useCars.ts", content=_use_cars_ts()),
        GeneratedFile(path="src/components/CarCard.tsx", content=_car_card_tsx()),
        GeneratedFile(path="src/components/AddCarForm.tsx", content=_add_car_form_tsx()),
        GeneratedFile(path="src/components/CarInventory.tsx", content=_car_inventory_tsx()),
        GeneratedFile(path="src/__tests__/CarInventory.test.tsx", content=_car_inventory_test_tsx()),
        GeneratedFile(path="src/App.tsx", content=_app_tsx()),
    ]


def _is_valid_generation(files: list[GeneratedFile], allowed: set[str]) -> bool:
    """Workflow fallback 2: Reject model output that drifts from the expected app shape."""
    file_map = {f.path: f.content for f in files}
    expected_required = {
        "src/hooks/useCars.ts",
        "src/components/CarCard.tsx",
        "src/components/AddCarForm.tsx",
        "src/components/CarInventory.tsx",
        "src/__tests__/CarInventory.test.tsx",
        "src/App.tsx",
    }

    if not expected_required.issubset(file_map):
        return False
    if any(path not in allowed for path in file_map):
        return False

    use_cars = file_map["src/hooks/useCars.ts"]
    if "export function useCars()" not in use_cars:
        return False
    if 'export type SortOption = "year-desc" | "year-asc" | "make-asc" | "make-desc";' not in use_cars:
        return False
    if "GET_CAR" in use_cars:
        return False

    add_car_form = file_map["src/components/AddCarForm.tsx"]
    if 'import type { AddCarInput } from "@/hooks/useCars";' not in add_car_form:
        return False
    if 'import { useCars } from "@/hooks/useCars";' in add_car_form:
        return False
    if "Image URL" in add_car_form:
        return False

    car_card = file_map["src/components/CarCard.tsx"]
    if "react-router-dom" in car_card or "useRouter" in car_card:
        return False
    if "car.mobile" not in car_card or "car.tablet" not in car_card or "car.desktop" not in car_card:
        return False

    car_inventory = file_map["src/components/CarInventory.tsx"]
    if 'import { type SortOption, useCars } from "@/hooks/useCars";' not in car_inventory:
        return False
    if "sortedCars" in car_inventory or "setSearchModel" in car_inventory:
        return False

    test_file = file_map["src/__tests__/CarInventory.test.tsx"]
    if 'from "vitest"' not in test_file:
        return False
    if "import React" in test_file or "fireEvent" in test_file:
        return False

    app_file = file_map["src/App.tsx"]
    if 'import CarInventory from "@/components/CarInventory";' not in app_file:
        return False

    return True


def _use_cars_ts() -> str:
    """Workflow template 1: Build the reusable hook source returned by the fallback path."""
    return """import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@apollo/client";
import { ADD_CAR, GET_CARS } from "@/graphql/queries";
import type { Car } from "@/types";

type CarsQueryData = {
  cars: Car[];
};

type AddCarMutationData = {
  addCar: Car;
};

type AddCarVariables = {
  make: string;
  model: string;
  year: number;
  color: string;
};

export type SortOption = "year-desc" | "year-asc" | "make-asc" | "make-desc";

export type AddCarInput = AddCarVariables;

export function useCars() {
  const { data, loading, error } = useQuery<CarsQueryData>(GET_CARS);
  const [searchTerm, setSearchTerm] = useState("");
  const [sortBy, setSortBy] = useState<SortOption>("year-desc");
  const [addCarMutation, addCarState] = useMutation<AddCarMutationData, AddCarVariables>(
    ADD_CAR,
    {
      refetchQueries: [{ query: GET_CARS }],
    }
  );

  const cars = useMemo(() => {
    const normalizedQuery = searchTerm.trim().toLowerCase();
    const filteredCars = (data?.cars ?? []).filter((car) =>
      car.model.toLowerCase().includes(normalizedQuery)
    );
    const sortedCars = [...filteredCars];

    sortedCars.sort((left, right) => {
      if (sortBy === "year-asc") {
        return left.year - right.year;
      }
      if (sortBy === "year-desc") {
        return right.year - left.year;
      }
      if (sortBy === "make-asc") {
        return left.make.localeCompare(right.make);
      }
      return right.make.localeCompare(left.make);
    });

    return sortedCars;
  }, [data?.cars, searchTerm, sortBy]);

  const addCar = async (input: AddCarInput) => {
    await addCarMutation({
      variables: input,
    });
  };

  return {
    cars,
    loading,
    error,
    searchTerm,
    setSearchTerm,
    sortBy,
    setSortBy,
    addCar,
    addCarState,
  };
}
"""


def _car_card_tsx() -> str:
    """Workflow template 2: Build the responsive card component source for the fallback path."""
    return """import { Card, CardContent, CardMedia, Chip, Stack, Typography, useMediaQuery } from "@mui/material";
import type { Car } from "@/types";

type CarCardProps = {
  car: Car;
};

export default function CarCard({ car }: CarCardProps) {
  const isMobile = useMediaQuery("(max-width:640px)");
  const isTablet = useMediaQuery("(min-width:641px) and (max-width:1023px)");
  const imageSrc = isMobile ? car.mobile : isTablet ? car.tablet : car.desktop;

  return (
    <Card elevation={2} sx={{ overflow: "hidden" }}>
      <CardMedia
        component="img"
        height="220"
        image={imageSrc}
        alt={`${car.year} ${car.make} ${car.model}`}
      />
      <CardContent>
        <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={2}>
          <div>
            <Typography variant="h6">
              {car.year} {car.make} {car.model}
            </Typography>
            <Typography color="text.secondary">{car.color}</Typography>
          </div>
          <Chip label={car.make} color="primary" variant="outlined" />
        </Stack>
      </CardContent>
    </Card>
  );
}
"""


def _add_car_form_tsx() -> str:
    """Workflow template 3: Build the add-car form source for the fallback path."""
    return """import { type FormEvent, useMemo, useState } from "react";
import { Alert, Box, Button, Card, CardContent, Stack, TextField, Typography } from "@mui/material";
import type { AddCarInput } from "@/hooks/useCars";

type AddCarFormProps = {
  isSubmitting: boolean;
  errorMessage?: string;
  onSubmit: (input: AddCarInput) => Promise<void>;
};

const DEFAULT_YEAR = "2026";

export default function AddCarForm({ isSubmitting, errorMessage, onSubmit }: AddCarFormProps) {
  const [make, setMake] = useState("");
  const [model, setModel] = useState("");
  const [year, setYear] = useState(DEFAULT_YEAR);
  const [color, setColor] = useState("");

  const isValid = useMemo(() => {
    const parsedYear = Number(year);
    return (
      make.trim().length > 0 &&
      model.trim().length > 0 &&
      color.trim().length > 0 &&
      Number.isInteger(parsedYear) &&
      parsedYear >= 1886 &&
      parsedYear <= 2100
    );
  }, [color, make, model, year]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isValid || isSubmitting) {
      return;
    }

    try {
      await onSubmit({
        make: make.trim(),
        model: model.trim(),
        year: Number(year),
        color: color.trim(),
      });
    } catch {
      return;
    }

    setMake("");
    setModel("");
    setYear(DEFAULT_YEAR);
    setColor("");
  };

  return (
    <Card elevation={3}>
      <CardContent>
        <Box component="form" onSubmit={handleSubmit}>
          <Stack spacing={2}>
            <Typography variant="h5">Add Car</Typography>
            <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
              <TextField
                label="Make"
                value={make}
                onChange={(event) => setMake(event.target.value)}
                fullWidth
              />
              <TextField
                label="Model"
                value={model}
                onChange={(event) => setModel(event.target.value)}
                fullWidth
              />
            </Stack>
            <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
              <TextField
                label="Year"
                value={year}
                onChange={(event) => setYear(event.target.value)}
                inputMode="numeric"
                fullWidth
              />
              <TextField
                label="Color"
                value={color}
                onChange={(event) => setColor(event.target.value)}
                fullWidth
              />
            </Stack>
            {errorMessage ? <Alert severity="error">{errorMessage}</Alert> : null}
            <Button type="submit" variant="contained" disabled={!isValid || isSubmitting}>
              {isSubmitting ? "Saving..." : "Add Car"}
            </Button>
          </Stack>
        </Box>
      </CardContent>
    </Card>
  );
}
"""


def _car_inventory_tsx() -> str:
    """Workflow template 4: Build the inventory screen source for the fallback path."""
    return """import { Alert, Box, CircularProgress, Container, FormControl, InputLabel, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import AddCarForm from "@/components/AddCarForm";
import CarCard from "@/components/CarCard";
import { type SortOption, useCars } from "@/hooks/useCars";

const sortLabels: Array<{ value: SortOption; label: string }> = [
  { value: "year-desc", label: "Year (Newest)" },
  { value: "year-asc", label: "Year (Oldest)" },
  { value: "make-asc", label: "Make (A-Z)" },
  { value: "make-desc", label: "Make (Z-A)" },
];

export default function CarInventory() {
  const {
    cars,
    loading,
    error,
    searchTerm,
    setSearchTerm,
    sortBy,
    setSortBy,
    addCar,
    addCarState,
  } = useCars();

  const handleAddCar = async (
    input: Parameters<typeof addCar>[0]
  ) => {
    await addCar(input);
  };

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      <Stack spacing={3}>
        <Box>
          <Typography variant="h3" component="h1" gutterBottom>
            Car Inventory Manager
          </Typography>
          <Typography color="text.secondary">
            Search by model, sort by make or year, and add new inventory in one place.
          </Typography>
        </Box>

        <AddCarForm
          isSubmitting={addCarState.loading}
          errorMessage={addCarState.error?.message}
          onSubmit={handleAddCar}
        />

        <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
          <TextField
            label="Search by model"
            placeholder="e.g. Civic"
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
            fullWidth
          />
          <FormControl sx={{ minWidth: { xs: "100%", md: 220 } }}>
            <InputLabel id="sort-cars-label">Sort cars</InputLabel>
            <Select
              labelId="sort-cars-label"
              label="Sort cars"
              value={sortBy}
              onChange={(event) => setSortBy(event.target.value as SortOption)}
            >
              {sortLabels.map((option) => (
                <MenuItem key={option.value} value={option.value}>
                  {option.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </Stack>

        {loading ? <CircularProgress /> : null}
        {error ? <Alert severity="error">{error.message}</Alert> : null}

        {!loading && !error ? (
          <Stack spacing={2}>
            {cars.length > 0 ? (
              cars.map((car) => <CarCard key={car.id} car={car} />)
            ) : (
              <Alert severity="info">No cars match your current search.</Alert>
            )}
          </Stack>
        ) : null}
      </Stack>
    </Container>
  );
}
"""


def _car_inventory_test_tsx() -> str:
    """Workflow template 5: Build the generated test suite source for the fallback path."""
    return """import { render, screen, waitFor } from "@testing-library/react";
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
"""


def _app_tsx() -> str:
    """Workflow template 6: Build the minimal App shell that mounts the generated inventory."""
    return """import CarInventory from "@/components/CarInventory";

export default function App() {
  return <CarInventory />;
}
"""
