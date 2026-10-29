// SPDX-License-Identifier: Apache-2.0
#include "tracker_3d.hpp"
#include <cassert>
#include <limits>
int main() {
  assert(city::tracker_mode("camera-local")=="camera-local");
  assert(city::tracker_mode("mv3dt-diagnostic")=="mv3dt-diagnostic");
  assert(city::tracker_mode("mv3dt-demo")=="mv3dt-demo");
  bool promotion_rejected=false;
  try{city::tracker_mode("mv3dt");}
  catch(const std::runtime_error& error){promotion_rejected=std::string(error.what()).find("unqualified")!=std::string::npos;}
  assert(promotion_rejected);
  bool rejected=false;try{city::tracker_mode("unknown");}catch(const std::runtime_error&){rejected=true;}
  assert(rejected);
  assert(city::valid_world_foot(-23.3,78.6));
  assert(!city::valid_world_foot(std::numeric_limits<double>::quiet_NaN(),1));
  assert(!city::valid_world_foot(1e9,1));
  assert(city::valid_visibility(0)&&city::valid_visibility(1));
  assert(!city::valid_visibility(-1)&&!city::valid_visibility(1.01));
  assert(!city::valid_visibility(std::numeric_limits<double>::quiet_NaN()));
  assert(!city::valid_visibility(std::numeric_limits<double>::infinity()));
  std::string epoch="both-cameras-before-reset";
  city::retire_diagnostic_fusion_epoch(epoch,"camera-a-reset");
  assert(epoch=="camera-a-reset");
  city::retire_diagnostic_fusion_epoch(epoch,"camera-b-clock-basis-change");
  assert(epoch=="camera-b-clock-basis-change");
  for(const auto& invalid:{std::string(),epoch}) {
    bool reuse_rejected=false;
    try{city::retire_diagnostic_fusion_epoch(epoch,invalid);}
    catch(const std::runtime_error&){reuse_rejected=true;}
    assert(reuse_rejected&&epoch=="camera-b-clock-basis-change");
  }
  using Point=std::array<double,2>;
  const std::optional<Point> world=Point{-23,78},image=Point{640,360};
  const auto allowed=[&](const std::string& mode,unsigned cls,bool observed,const std::string& clock,
                         std::optional<Point> w,std::optional<Point> i,std::optional<double> visibility) {
    return city::demo_global_identity(mode,cls,observed,clock,w,i,visibility,epoch,25);
  };
  assert(allowed("mv3dt-demo",0,true,"source-rtcp",world,image,.25)=="mv3dt-demo:"+epoch+":25");
  assert(allowed("mv3dt-demo",0,true,"source-rtcp",world,image,1));
  for(const auto& mode:{"camera-local","mv3dt-diagnostic","mv3dt"})
    assert(!allowed(mode,0,true,"source-rtcp",world,image,1));
  for(unsigned cls=1;cls<=6;cls++)assert(!allowed("mv3dt-demo",cls,true,"source-rtcp",world,image,1));
  assert(!allowed("mv3dt-demo",0,false,"source-rtcp",world,image,1));
  for(const auto& basis:{"recorded-pts","arrival-pts-unsynchronized",""})
    assert(!allowed("mv3dt-demo",0,true,basis,world,image,1));
  for(double v:{0.,.249999,-1.,1.01,std::numeric_limits<double>::quiet_NaN(),std::numeric_limits<double>::infinity()})
    assert(!allowed("mv3dt-demo",0,true,"source-rtcp",world,image,v));
  assert(!allowed("mv3dt-demo",0,true,"source-rtcp",world,image,std::nullopt));
  assert(!allowed("mv3dt-demo",0,true,"source-rtcp",std::nullopt,image,1));
  assert(!allowed("mv3dt-demo",0,true,"source-rtcp",world,std::nullopt,1));
  assert(!allowed("mv3dt-demo",0,true,"source-rtcp",Point{1,std::numeric_limits<double>::quiet_NaN()},image,1));
  assert(!allowed("mv3dt-demo",0,true,"source-rtcp",world,Point{std::numeric_limits<double>::infinity(),1},1));
  assert(!city::demo_global_identity("mv3dt-demo",0,true,"source-rtcp",world,image,1,"",25));
  assert(!city::demo_global_identity("mv3dt-demo",0,true,"source-rtcp",world,image,1,epoch,std::numeric_limits<uint64_t>::max()));
  city::DemoTrackIdCounts ids;
  // Reproduce two SDK objects with ID9; a third occurrence remains omitted.
  for(uint64_t id:{9,113,9,62,9})ids.observe(id);
  assert(ids.reject(9)&&!ids.reject(113)&&!ids.reject(62));
  assert(ids.duplicate_ids==1&&ids.omitted_objects()==3);
  // The helper deliberately ignores class/visibility/confidence: even a
  // person and car sharing an SDK ID must both be omitted, never selected.
  city::DemoTrackIdCounts cross_class;
  for(const auto& object:std::array<std::pair<uint64_t,unsigned>,3>{{{42,0},{7,0},{42,2}}})cross_class.observe(object.first);
  assert(cross_class.reject(42)&&!cross_class.reject(7));
  assert(cross_class.duplicate_ids==1&&cross_class.omitted_objects()==2);
  city::DemoTrackIdCounts next_frame;next_frame.observe(9);
  assert(!next_frame.reject(9)&&next_frame.omitted_objects()==0);
  next_frame.observe(std::numeric_limits<uint64_t>::max());
  assert(next_frame.total_objects==1);
  city::DemoTrackIdCounts bounded;
  for(uint64_t id=0;id<=city::DemoTrackIdCounts::maximum_distinct_ids;id++)bounded.observe(id);
  assert(bounded.capacity_exceeded&&bounded.counts.size()==city::DemoTrackIdCounts::maximum_distinct_ids);
  assert(bounded.reject(0)&&bounded.reject(city::DemoTrackIdCounts::maximum_distinct_ids));
  assert(bounded.omitted_objects()==city::DemoTrackIdCounts::maximum_distinct_ids+1);
}
