"""GPU regression: real-mesh captures, day/night, prism/sprite pixels and depth.

Run with the managed Python. Writes a review image under output/building_lod/.
"""
import os
import sys
from types import SimpleNamespace

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import pyray as rl
import buildinglod as lod


def pixels(rt):
    img = rl.load_image_from_texture(rt.texture)
    colors = rl.load_image_colors(img)
    data = np.frombuffer(rl.ffi.buffer(colors, img.width*img.height*4),np.uint8).copy().reshape(img.height,img.width,4)
    rl.unload_image_colors(colors)
    rl.unload_image(img)
    return data[::-1]


def main():
    rl.set_trace_log_level(rl.LOG_WARNING)
    rl.set_config_flags(rl.FLAG_WINDOW_HIDDEN)
    rl.init_window(512,512,"Building LOD regression")
    lo, hi = [-12,0,-8], [12,36,8]
    pos = np.asarray(lod.prism_vertices(lo,hi),np.float32)
    uv = np.asarray([q for _ in range(5) for q in ((0,1),(1,1),(1,0),(0,1),(1,0),(0,0))],np.float32)
    col = np.full((len(pos),4),255,np.uint8)
    # Different face colors expose mirrored, misplaced or missing captures.
    for i, c in enumerate(((230,170,120),(130,220,150),(130,160,240),(230,200,140),(180,90,70))):
        col[i*6:i*6+6,:3] = c
    image = rl.gen_image_checked(64,64,8,8,rl.WHITE,rl.Color(35,40,45,255))
    tex = rl.load_texture_from_image(image)
    rl.unload_image(image)
    offset = np.array([35,0,-15],np.float32)
    arrays = np.concatenate([pos,pos+offset]),np.tile(uv,(2,1)),np.concatenate([col,col[:,[2,1,0,3]]])
    records = [(lo,hi,[(0,0,len(pos))]),
               ((np.array(lo)+offset).tolist(),(np.array(hi)+offset).tolist(),[(0,len(pos),len(pos))])]
    world = SimpleNamespace(chunks={(0,0):{"lod":records,"m":{0:(0,len(arrays[0]))}}},mesh_arrays=lambda off,n:arrays)
    captures = lod.Captures(world,{"A":tex})
    for _ in records:
        captures.prepare([(0,0)],1000)
    assert captures.groups[((0,0),0)]["models"], "capture never completed"
    emission = pixels(captures.groups[((0,0),0)]["atlases"][1])
    assert emission[:lod.SIZE,:lod.SIZE*4,:3].sum() > 1000, "captured windows have no emission"
    assert emission[:lod.SIZE,lod.SIZE*4:,:3].max() == 0, "roof glows like a window"
    rt = rl.load_render_texture(512,512)
    frames = []
    try:
        for eye in ((85,65,120),(-95,55,-110),(0,100,0),(0,30,140)):
            cam = rl.Camera3D(rl.Vector3(*eye),rl.Vector3(0,18,0),
                              rl.Vector3(0,0,-1) if eye[2] == 0 else rl.Vector3(0,1,0),38,rl.CAMERA_PERSPECTIVE)
            pair = []
            for dark in (0.0,1.0):
                for sprite in (False,True):
                    lod.SPRITE_DISTANCE = 0 if sprite else 1e9
                    rl.rl_set_clip_planes(0.5,2600)
                    rl.begin_texture_mode(rt)
                    rl.clear_background(rl.Color(25,30,45,255))
                    rl.begin_mode_3d(cam)
                    rl.rl_disable_backface_culling()
                    assert captures.draw((0,0),cam,dark)
                    # A foreground object must occlude both LODs identically.
                    rl.draw_cube(rl.Vector3(0,15,12),8,15,5,rl.Color(100,50,150,255))
                    rl.end_mode_3d()
                    if dark:
                        rl.begin_blend_mode(rl.BLEND_MULTIPLIED)
                        rl.draw_rectangle(0,0,512,512,rl.Color(80,95,155,255))
                        rl.end_blend_mode()
                        rl.begin_mode_3d(cam)
                        rl.rl_disable_backface_culling()
                        rl.rl_disable_depth_mask()
                        rl.begin_blend_mode(rl.BLEND_ADDITIVE)
                        assert captures.draw((0,0),cam,dark,glow=True)
                        rl.end_blend_mode()
                        rl.rl_enable_depth_mask()
                        rl.end_mode_3d()
                    rl.end_texture_mode()
                    pair.append(pixels(rt))
                diff = np.abs(pair[-1].astype(int)-pair[-2].astype(int))
                print(eye,dark,"LOD difference",float(diff.mean()))
                if diff.mean() >= 0.15:
                    os.makedirs("output/building_lod",exist_ok=True)
                    Image.fromarray(np.concatenate(pair[-2:],axis=1)).save("output/building_lod/mismatch.png")
                assert diff.mean() < 0.15, f"prism/sprite mismatch: {diff.mean():.4f}"
                assert np.count_nonzero(np.any(pair[-1][:,:,:3] != (25,30,45),axis=2)) > 1000, "empty LOD image"
            delta = np.abs(pair[0].astype(int)-pair[2].astype(int)).sum()
            print(eye, "night delta", delta)
            if eye[2] != 0:
                assert delta > 1000, "night windows missing"
            frames.extend(pair)
        os.makedirs("output/building_lod",exist_ok=True)
        sheet = np.concatenate([np.concatenate(frames[i:i+4],axis=1) for i in range(0,len(frames),4)],axis=0)
        Image.fromarray(sheet).save("output/building_lod/day_night_prism_sprite.png")
        print("PASS: four views; day/night prism and sprite match, foreground depth preserved")
    finally:
        captures.close()
        rl.unload_texture(tex)
        rl.unload_render_texture(rt)
        rl.close_window()


if __name__ == "__main__":
    main()
