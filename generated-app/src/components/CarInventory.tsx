import { Alert, Box, CircularProgress, Container, FormControl, InputLabel, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
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
