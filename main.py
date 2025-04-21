# -*- coding:utf-8 -*-
try:
    from typing import List, Tuple, Dict, Any, Optional
except ImportError:
    pass

import Rhino.Geometry as geo  # type: ignore
import scriptcontext as sc  # type: ignore
import Rhino  # type: ignore
import ghpythonlib.components as ghcomp  # type: ignore
import utils

# 모듈 새로고침
import importlib

importlib.reload(utils)


class Lot:
    def __init__(self, region: geo.Curve, district_use: str) -> None:
        self.region = region
        self.district_use = district_use
        self.area = geo.AreaMassProperties.Compute(region).Area


class Road:
    def __init__(self, curve: geo.Curve) -> None:
        self.curve = curve


class Building:
    def __init__(self, regions: List[geo.Curve], floor_count: int, use: str) -> None:
        self.regions = regions
        self.floor_area = sum(
            geo.AreaMassProperties.Compute(region).Area for region in regions
        )
        self.floor_count = floor_count
        self.total_area = self.floor_area * floor_count
        self.use = use


class OpenspaceRequirement:
    """공개공지 설치 조건"""

    MIN_AREA = 90.0  # type: float
    MIN_DEPTH = 9.0  # type: float
    AREA_RATIO = 0.1  # type: float
    # 최대 넓이 도로변과 4분의1이상 접할 것
    ROAD_ADJUST_RATIO = 0.25  # type: float

    def __init__(self, lot: Lot, building: Building) -> None:
        self.area = 0  # type: float
        self._get_target_information(lot, building)

    def _get_target_information(self, lot: Lot, building: Building) -> None:
        # 공개공지 설치 조건
        # 1. 대지의 용도 조건
        if lot.district_use not in (
            "일반주거지역",
            "준주거지역",
            "상업지역",
            "준공업지역",
        ):
            return
        # 2. 건축물의 용도 조건
        if building.use not in (
            "문화시설",
            "집회시설",
            "종교시설",
            "판매시설",
            "운수시설",
            "업무시설",
            "숙박시설",
        ):
            return

        # 3. 건축물의 연면적 조건
        if building.total_area < 5000:
            return

        # 공개공지 면적 = 대지면적의 10%이상(최소 90m2)
        self.area = max(lot.area * self.AREA_RATIO, self.MIN_AREA)


class OepnspaceGenerator:
    def __init__(
        self,
        lot: Lot,
        roads: List[Road],
        building: Building,
        parking_region: geo.Curve,
        requirement: OpenspaceRequirement,
    ) -> None:
        self.lot = lot
        self.roads = roads
        self.building = building
        self.parking_region = parking_region
        self.requirement = requirement

    def get_openspace(self) -> List[geo.Curve]:
        # 공개공지 생성 로직
        # 1. 후보 지역 생성
        candidates = self.get_candidate_regions()

        # 2. 후보 지역 필터링
        filtered_candidates = self.filter_candidate_regions(candidates)

        # 3. 후보 지역 정렬
        sorted_candidates = self.sort_candidate_regions(filtered_candidates)

        # 4. 후보 지역 조정(축소)
        return self.adjust_candidate_regions(sorted_candidates)

    def get_candidate_regions(self) -> List[geo.Curve]:
        """공개공지 최소 조건을 만족하는 영역 생성"""
        # 최소 폭 조거늘 만족하는 영역 확보
        # 오프셋 in and out 을 통해 확보
        inward_regions = utils.offset_regions_inward(
            [self.lot.region, self.parking_region] + self.building.regions,
            self.requirement.MIN_DEPTH / 2,
        )

        # 빌딩영역과 교차가 있는 경우 필터링 geo.Curve.PlanarCurveCollision 사용
        filtered_inward_regions = []
        for region in inward_regions:
            if any(
                utils.has_region_intersection(region, other_region)
                for other_region in self.building.regions
            ):
                continue
            filtered_inward_regions.append(region)

        candidate_regions = utils.offset_regions_outward(
            filtered_inward_regions, self.requirement.MIN_DEPTH / 2
        )

        return candidate_regions

    def filter_candidate_regions(self, candidates: List[geo.Curve]) -> List[geo.Curve]:
        """후보 지역 필터링"""

        def is_road_adjacent(candidate: geo.Curve) -> bool:
            # 도로와 후보 지역의 접촉 여부 확인
            for road in self.roads:
                candidate_overlap_length = utils.get_overlap_length(
                    candidate, road.curve
                )
                lot_overlap_length = utils.get_overlap_length(
                    self.lot.region, road.curve
                )
                if (
                    candidate_overlap_length
                    > lot_overlap_length * self.requirement.ROAD_ADJUST_RATIO
                ):
                    return True

            return False

        # 도로와 4분의 1 이상 접하는 후보 지역 필터링
        filtered_candidates = filter(lambda x: is_road_adjacent(x), candidates)

        # 공개공지 면적 조건 필터링
        filtered_candidates = filter(
            lambda x: geo.AreaMassProperties.Compute(x).Area
            >= self.requirement.MIN_AREA,
            filtered_candidates,
        )

        return list(filtered_candidates)

    def sort_candidate_regions(self, candidates: List[geo.Curve]) -> List[geo.Curve]:
        # 후보 지역 정렬 로직
        sorted_candidates = sorted(
            candidates,
            key=lambda x: geo.AreaMassProperties.Compute(x).Area,
            reverse=True,
        )
        return sorted_candidates

    def adjust_candidate_regions(self, candidates: List[geo.Curve]) -> List[geo.Curve]:
        # 후보 지역 조정 로직
        def reduce_region(region: geo.Curve, target_area: float) -> geo.Curve:
            # 후보 지역을 목표 면적에 맞게 조정
            region = region.Duplicate()
            area = geo.AreaMassProperties.Compute(region).Area
            if area <= target_area:
                return region
            scale_factor = (target_area / area) ** 0.5
            center_of_scale = utils.get_overlap_crv(region, self.lot.region)[0].PointAt(
                0.5
            )
            return ghcomp.Scale(region, center_of_scale, scale_factor).geometry

        adjusted_candidates = []
        total_area = 0.0
        # 후보 영역을 목표 면적에 도달할때 까지 확보
        for candidate in candidates:
            area = geo.AreaMassProperties.Compute(candidate).Area
            if total_area + area > self.requirement.area:
                candidate = reduce_region(candidate, self.requirement.area - total_area)
                area = geo.AreaMassProperties.Compute(candidate).Area

            adjusted_candidates.append(candidate)
            total_area += area

            if total_area >= self.requirement.area:
                break

        return adjusted_candidates


lot = Lot(lot_region, "일반주거지역")  # type: geo.Curve
roads = [Road(region) for region in road_regions]  # type: List[Road]
building = Building(building_regions, 5, "업무시설")  # Placeholder for building
requirement = OpenspaceRequirement(lot, building)  # Placeholder for requirement
openspace_generator = OepnspaceGenerator(
    lot, roads, building, parking_region, requirement
)  # type: OepnspaceGenerator

openspace_regions = openspace_generator.get_openspace()

openspace_area = sum(
    geo.AreaMassProperties.Compute(region).Area for region in openspace_regions
)
print(f"Total Openspace Area: {openspace_area} m2")
print(f"Lot Area: {lot.area} m2")
print(f"Building Area: {building.floor_area} m2")
