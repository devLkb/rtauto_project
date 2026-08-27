using System.Collections.Generic;
using UnityEngine;

namespace KDT.PicknPlaceTraining
{
    /// <summary>
    /// Reports contact between one moving arm collider and any of a fixed set of
    /// unsafe surfaces (the floor panel). Hand links are deliberately NOT
    /// instrumented: the fingers have to work right at the floor surface to grasp
    /// the cube, so treating their contact as a safety failure would make the task
    /// impossible.
    ///
    /// Ported from GraspLift's GraspLiftSurfaceContactSensor, generalized from a
    /// single unsafe surface to an array (currently populated with just the panel).
    /// </summary>
    public sealed class PicknPlaceSurfaceContactSensor : MonoBehaviour
    {
        public Dg5fPicknPlaceAgent agent;
        public Collider[] unsafeSurfaces = System.Array.Empty<Collider>();

        readonly HashSet<Collider> _contacts = new HashSet<Collider>();

        public bool HasUnsafeContact => _contacts.Count > 0;

        public void ResetContacts()
        {
            _contacts.Clear();
        }

        Collider FindUnsafeSurface(Collider other)
        {
            if (other == null || unsafeSurfaces == null) return null;
            foreach (var surface in unsafeSurfaces)
            {
                if (surface == null) continue;
                if (other == surface || other.transform.IsChildOf(surface.transform))
                    return surface;
            }
            return null;
        }

        void Register(Collider other)
        {
            Collider surface = FindUnsafeSurface(other);
            if (surface == null) return;
            _contacts.Add(other);
            if (agent != null) agent.NotifyUnsafeSurfaceContact(surface);
        }

        void OnCollisionEnter(Collision collision)
        {
            if (collision != null) Register(collision.collider);
        }

        void OnCollisionStay(Collision collision)
        {
            if (collision != null) Register(collision.collider);
        }

        void OnCollisionExit(Collision collision)
        {
            if (collision != null && collision.collider != null)
                _contacts.Remove(collision.collider);
        }

        void OnDisable()
        {
            _contacts.Clear();
        }
    }
}
