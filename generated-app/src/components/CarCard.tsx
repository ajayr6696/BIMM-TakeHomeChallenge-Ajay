import { Card, CardContent, CardMedia, Chip, Stack, Typography, useMediaQuery } from "@mui/material";
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
