import { useMemo, useState } from "react";
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
