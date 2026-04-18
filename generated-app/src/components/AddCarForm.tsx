import { type FormEvent, useMemo, useState } from "react";
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
