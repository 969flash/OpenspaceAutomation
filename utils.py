# -*- coding:utf-8 -*-
try:
    from typing import List, Tuple, Dict, Any, Optional, Union
except ImportError:
    pass
import functools

import Rhino
import Rhino.Geometry as geo  # ignore
import ghpythonlib.components as ghcomp  # ignore

BIGNUM = 10000000

TOL = 0.001
DIST_TOL = 0.01
AREA_TOL = 0.1
OP_TOL = 0.00001
CLIPPER_TOL = 0.0000000001


def get_overlap_crv(crv_a: geo.Curve, crv_b: geo.Curve) -> List[geo.Curve]:
    """두 커브의 겹치는 구간을 구한다.
    Args:
        crv_a : crv_b과 겹치는 부분을 구할 커브
        crv_b : crv_a과 겹치짐을 테스트할 커브

    Returns:
        crv_a를 기준으로 crv_b와 겹치는 부분 커브
    """
    # 두 커브가 교차조차 없으면 겹치는 부분이 없다.
    if not geo.Curve.PlanarCurveCollision(crv_a, crv_b, geo.Plane.WorldXY, TOL):
        return []

    # crv_a와 crv_b의 교차점 + crv_a의 꼭짓점들로 crv_a를 자른다.
    pts_to_split = (
        ghcomp.Explode(crv_a, True).vertices + ghcomp.CurveXCurve(crv_a, crv_b).points
    )
    if not pts_to_split:
        return []

    parameters = [ghcomp.CurveClosestPoint(pt, crv_a).parameter for pt in pts_to_split]

    segments = ghcomp.Shatter(crv_a, parameters)

    overlaped_segments = [
        seg
        for seg in segments
        if geo.Curve.PlanarCurveCollision(seg, crv_b, geo.Plane.WorldXY, TOL)
    ]

    if not overlaped_segments:
        return []

    return geo.Curve.JoinCurves(overlaped_segments)


def get_overlap_length(crv_a: geo.Curve, crv_b: geo.Curve) -> float:
    """두 커브의 겹치는 길이를 구한다.
    Args:
        crv_a : crv_b과 겹치는 부분을 구할 커브
        crv_b : crv_a과 겹치짐을 테스트할 커브

    Returns:
        crv_a를 기준으로 crv_b와 겹치는 부분 길이
    """
    overlap_crvs = get_overlap_crv(crv_a, crv_b)
    if not overlap_crvs:
        return 0.0

    length = 0.0
    for crv in overlap_crvs:
        length += crv.GetLength()
    return length


def is_intersection_with_other_crvs(crv: geo.Curve, crvs: List[geo.Curve]) -> bool:
    return any(
        geo.Curve.PlanarCurveCollision(crv, other_crv, geo.Plane.WorldXY, OP_TOL)
        for other_crv in crvs
    )


def has_region_intersection(
    region: geo.Curve, other_region: geo.Curve, tol: float = TOL
) -> bool:
    """영역 커브와 다른 영역 커브가 교차하는지 확인한다.
    Args:
        region: 영역 커브
        other_regions: 다른 영역 커브 리스트
        tol: tolerance

    Returns:
        bool: 교차 여부
    """
    relationship = geo.Curve.PlanarClosedCurveRelationship(
        region, other_region, geo.Plane.WorldXY, tol
    )
    # 완전히 떨어져 있는 경우. 닿은 부분 없이.
    if relationship == geo.RegionContainment.Disjoint:
        return False
    return True


def offset_regions_inward(
    regions: Union[geo.Curve, List[geo.Curve]], dist: float, miter: int = BIGNUM
) -> List[geo.Curve]:
    """영역 커브를 안쪽으로 offset 한다.
    단일커브나 커브리스트 관계없이 커브 리스트로 리턴한다.
    Args:
        region: offset할 대상 커브
        dist: offset할 거리

    Returns:
        offset 후 커브
    """

    if not dist:
        return regions
    return Offset().polyline_offset(regions, dist, miter).holes


def offset_regions_outward(
    regions: Union[geo.Curve, List[geo.Curve]], dist: float, miter: int = BIGNUM
) -> List[geo.Curve]:
    """영역 커브를 바깥쪽으로 offset 한다.
    단일커브나 커브리스트 관계없이 커브 리스트로 리턴한다.
    Args:
        region: offset할 대상 커브
        dist: offset할 거리
    returns:
        offset 후 커브
    """
    if isinstance(regions, geo.Curve):
        regions = [regions]

    return [offset_region_outward(region, dist, miter) for region in regions]


def offset_region_outward(
    region: geo.Curve, dist: float, miter: float = BIGNUM
) -> geo.Curve:
    """영역 커브를 바깥쪽으로 offset 한다.
    단일 커브를 받아서 단일 커브로 리턴한다.
    Args:
        region: offset할 대상 커브
        dist: offset할 거리

    Returns:
        offset 후 커브
    """

    if not dist:
        return region
    if not isinstance(region, geo.Curve):
        raise ValueError("region must be curve")
    return Offset().polyline_offset(region, dist, miter).contour[0]


def convert_io_to_list(func):
    """인풋과 아웃풋을 리스트로 만들어주는 데코레이터"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        new_args = []
        for arg in args:
            if isinstance(arg, geo.Curve):
                arg = [arg]
            new_args.append(arg)

        result = func(*new_args, **kwargs)
        if isinstance(result, geo.Curve):
            result = [result]

        if hasattr(result, "__dict__"):
            for key, values in result.__dict__.items():
                if isinstance(values, geo.Curve):
                    setattr(result, key, [values])
        return result

    return wrapper


class Offset:
    class _PolylineOffsetResult:
        def __init__(self):
            self.contour: Optional[List[geo.Curve]] = None
            self.holes: Optional[List[geo.Curve]] = None

    @convert_io_to_list
    def polyline_offset(
        self,
        crvs: List[geo.Curve],
        dists: List[float],
        miter: int = BIGNUM,
        closed_fillet: int = 2,
        open_fillet: int = 2,
        tol: float = Rhino.RhinoMath.ZeroTolerance,
    ) -> _PolylineOffsetResult:
        """
        Args:
            crv (_type_): _description_
            dists (_type_): _description_
            miter : miter
            closed_fillet : 0 = round, 1 = square, 2 = miter
            open_fillet : 0 = round, 1 = square, 2 = butt

        Returns:
            _type_: _PolylineOffsetResult
        """
        if not crvs:
            raise ValueError("No Curves to offset")

        plane = geo.Plane(geo.Point3d(0, 0, crvs[0].PointAtEnd.Z), geo.Vector3d.ZAxis)
        result = ghcomp.ClipperComponents.PolylineOffset(
            crvs,
            dists,
            plane,
            tol,
            closed_fillet,
            open_fillet,
            miter,
        )

        polyline_offset_result = Offset._PolylineOffsetResult()
        for name in ("contour", "holes"):
            setattr(polyline_offset_result, name, result[name])
        return polyline_offset_result
